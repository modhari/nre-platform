"""
server.py — lattice-mcp FastAPI server.

Responsibilities:
  - Expose /mcp/capability/{name} POST endpoints for BGP history queries
    and remediation planning.
  - Maintain a single BgpRouteStateTracker and BgpHistoryStore for the
    lifetime of the process.
  - On startup: load persisted history from disk, then seed with demo
    data if the store is still empty. This means the system is
    immediately useful after a cold start and gets richer as real data
    arrives.
  - On every write: the store auto-persists to disk via its persist_dir
    so history survives pod restarts.

Environment variables:
  BGP_HISTORY_PERSIST_DIR   path for JSON persistence files
                             default: /data/bgp_history
  BGP_HISTORY_AUTH_TOKEN    bearer token required on every request
                             default: local-dev-token
  MCP_AUDIT_LOG_PATH        path for JSONL audit log
                             default: /data/mcp_audit.jsonl
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from internal.bgp.anomaly_detector import BgpAnomalyDetector
from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.route_state_tracker import BgpRouteStateTracker, build_demo_routes
from internal.mcp.capability_registry import CapabilityRegistry

LOG = logging.getLogger(__name__)

# ── FastAPI application ───────────────────────────────────────────────────────
APP = FastAPI(title="Lattice MCP Server", version="0.2.0")


# ── Request model ─────────────────────────────────────────────────────────────

class CapabilityInvokeRequest(BaseModel):
    """Body accepted by every /mcp/capability/{name} endpoint."""
    payload: dict[str, Any] = Field(default_factory=dict)


# ── Idempotency store ─────────────────────────────────────────────────────────

@dataclass
class IdempotencyRecord:
    capability: str
    key: str
    response: dict[str, Any]
    created_at_ms: int


class InMemoryIdempotencyStore:
    """
    Idempotency guard for capability invocations.

    When a caller supplies the same X-Idempotency-Key for the same
    capability, the first response is replayed rather than re-executing.
    This protects against duplicate retries from nre-agent during
    transient network blips.
    """

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def get(self, capability: str, key: str) -> dict[str, Any] | None:
        record = self._records.get(f"{capability}:{key}")
        return record.response if record else None

    def put(self, capability: str, key: str, response: dict[str, Any]) -> None:
        self._records[f"{capability}:{key}"] = IdempotencyRecord(
            capability=capability,
            key=key,
            response=response,
            created_at_ms=_now_ms(),
        )


# ── Audit logger ──────────────────────────────────────────────────────────────

class JsonlAuditLogger:
    """
    Write one JSON line per capability invocation.

    Used for post-incident forensics. The file grows without bound —
    rotate or ship externally in production.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


# ── Module-level singletons (initialised in startup event) ───────────────────

_tracker:     BgpRouteStateTracker    | None = None
_store:       BgpHistoryStore         | None = None
_registry:    CapabilityRegistry      | None = None
_idempotency: InMemoryIdempotencyStore | None = None
_audit:       JsonlAuditLogger        | None = None


# ── Startup ───────────────────────────────────────────────────────────────────

@APP.on_event("startup")
def _startup() -> None:
    """
    Initialise all singletons on process start.

    Order:
    1. Create the store with persist_dir so writes go to disk.
    2. Load persisted history from disk.
    3. If the store is still empty, seed it with demo routes so the
       system is immediately queryable without waiting for live data.
    4. Wire the store into the capability registry.
    """
    global _tracker, _store, _registry, _idempotency, _audit

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # ── History persistence ───────────────────────────────────────────────────
    persist_dir = Path(
        os.getenv("BGP_HISTORY_PERSIST_DIR", "/data/bgp_history")
    )

    _store = BgpHistoryStore(persist_dir=persist_dir)
    _store.load_from_disk()

    # ── Route state tracker ───────────────────────────────────────────────────
    _tracker = BgpRouteStateTracker()

    # ── Seed with demo data if history is empty ───────────────────────────────
    # Ensures the system is queryable immediately on a fresh deployment.
    # Real snapshots pushed later will supplement and eventually dominate.
    if not _store.route_snapshots:
        LOG.info("History store is empty — seeding with demo routes")
        _seed_demo_data(_tracker, _store)
    else:
        LOG.info(
            "History store loaded %d snapshot rows from disk",
            len(_store.route_snapshots),
        )

    # ── Capability registry ───────────────────────────────────────────────────
    _registry = CapabilityRegistry(tracker=_tracker, history_store=_store)

    # ── Supporting services ───────────────────────────────────────────────────
    _idempotency = InMemoryIdempotencyStore()

    audit_path = Path(
        os.getenv("MCP_AUDIT_LOG_PATH", "/data/mcp_audit.jsonl")
    )
    _audit = JsonlAuditLogger(path=audit_path)

    LOG.info(
        "lattice-mcp ready — capabilities: %s",
        _registry.list_capabilities(),
    )


def _seed_demo_data(
    tracker: BgpRouteStateTracker,
    store: BgpHistoryStore,
) -> None:
    """
    Populate the tracker and history store with two demo snapshots.

    Snapshot 1 → Snapshot 2 shows one route removed (10.20.0.0/24),
    one added (10.40.0.0/24), and a local-pref change on the advertised
    route — enough to exercise anomaly detection and history queries
    without real device data.
    """
    snapshot_1, snapshot_2 = build_demo_routes()

    ts1 = snapshot_1[0].timestamp_ms
    ts2 = snapshot_2[0].timestamp_ms

    tracker.ingest_snapshot(ts1, snapshot_1)
    tracker.ingest_snapshot(ts2, snapshot_2)

    summaries_1 = tracker.peer_summaries_at(ts1)
    summaries_2 = tracker.peer_summaries_at(ts2)
    events      = tracker.route_events_for_diff(ts1, ts2)

    anomalies = BgpAnomalyDetector().detect_from_tracker(
        tracker=tracker,
        from_timestamp_ms=ts1,
        to_timestamp_ms=ts2,
    )

    store.store_route_snapshot_rows(snapshot_1)
    store.store_route_snapshot_rows(snapshot_2)
    store.store_peer_summary_rows(summaries_1)
    store.store_peer_summary_rows(summaries_2)
    store.store_route_event_rows(events)
    store.store_anomaly_rows(anomalies)

    LOG.info(
        "Demo seed complete — %d snapshots, %d events, %d anomalies",
        len(snapshot_1) + len(snapshot_2),
        len(events),
        len(anomalies),
    )


# ── Auth helper ───────────────────────────────────────────────────────────────

def _expected_token() -> str:
    return os.getenv("BGP_HISTORY_AUTH_TOKEN", "local-dev-token")


def _verify_auth(authorization: str | None) -> None:
    """
    Validate the Bearer token on every capability request.

    Uses secrets.compare_digest to prevent timing-oracle attacks.
    Raises HTTP 401 on failure.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, _expected_token()):
        raise HTTPException(status_code=401, detail="invalid bearer token")


# ── Capability endpoint ───────────────────────────────────────────────────────

@APP.post("/mcp/capability/{capability_name}")
async def invoke_capability(
    capability_name: str,
    body: CapabilityInvokeRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Unified capability invocation endpoint.

    All BGP capabilities share this route. The capability_name path
    parameter selects the handler from CapabilityRegistry.

    Supported capabilities:
      bgp_history_query       time-windowed route and event queries
      bgp_remediation_plan    read-only remediation planning
      bgp_remediation_execute write-path (gated by approval flag)
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
    _verify_auth(authorization)

    # ── Idempotency check ─────────────────────────────────────────────────────
    idempotency_key = request.headers.get("X-Idempotency-Key")
    if idempotency_key:
        cached = _idempotency.get(capability_name, idempotency_key)
        if cached is not None:
            LOG.info(
                "Idempotency hit — capability=%s key=%s",
                capability_name,
                idempotency_key,
            )
            return cached

    # ── Dispatch ──────────────────────────────────────────────────────────────
    handler = _registry.get_handler(capability_name)
    if handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown capability: {capability_name}",
        )

    try:
        response = handler(payload=body.payload)
    except Exception as exc:
        LOG.exception("Capability %s raised: %s", capability_name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ── Audit log ─────────────────────────────────────────────────────────────
    _audit.write({
        "ts_ms":           _now_ms(),
        "capability":      capability_name,
        "idempotency_key": idempotency_key,
        "payload_keys":    sorted(body.payload.keys()),
        "status":          "success",
    })

    # ── Cache for idempotency ─────────────────────────────────────────────────
    if idempotency_key:
        _idempotency.put(capability_name, idempotency_key, response)

    return response


# ── Health endpoints ──────────────────────────────────────────────────────────

@APP.get("/health/live")
def liveness() -> dict[str, str]:
    """Kubernetes liveness probe — returns 200 if the process is alive."""
    return {"status": "live"}


@APP.get("/health/ready")
def readiness() -> dict[str, Any]:
    """
    Kubernetes readiness probe — returns 200 only when the capability
    registry and history store are fully initialised.
    """
    if _registry is None or _store is None:
        raise HTTPException(status_code=503, detail="not ready")

    return {
        "status":        "ready",
        "capabilities":  _registry.list_capabilities(),
        "snapshot_rows": len(_store.route_snapshots),
        "event_rows":    len(_store.route_events),
        "anomaly_rows":  len(_store.anomalies),
    }


# ── Utility ───────────────────────────────────────────────────────────────────

def _now_ms() -> int:
    return int(time.time() * 1000)
