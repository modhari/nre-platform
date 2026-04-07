"""
history_store.py — BGP route history store with optional disk persistence.

Responsibilities:
  - Hold four in-memory tables: route_snapshots, peer_summaries,
    route_events, and anomalies.
  - Serve time-windowed queries used by BgpHistoryQueryService and
    BgpCrossDeviceCorrelator.
  - Optionally persist all tables to disk as JSON files so history
    survives a pod restart. Set persist_dir to a mounted PVC path to
    enable this. Leave as None (default) for fully in-memory operation.

Upgrade path:
  The public query interface maps cleanly to SQL. When data volume
  outgrows in-memory storage, swap this class for a ClickHouse-backed
  implementation — no callers need to change.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from internal.bgp.anomaly_detector import BgpAnomaly
from internal.bgp.models import (
    BgpPeerRouteSummary,
    BgpRouteEvent,
    BgpRouteRecord,
)
from internal.bgp.storage_models import (
    BgpAnomalyRow,
    BgpPeerRouteSummaryRow,
    BgpRouteEventRow,
    BgpRouteSnapshotRow,
)

LOG = logging.getLogger(__name__)

# ── Names of the JSON files written inside persist_dir ───────────────────────
_FILE_SNAPSHOTS = "bgp_route_snapshots.json"
_FILE_SUMMARIES = "bgp_peer_summaries.json"
_FILE_EVENTS    = "bgp_route_events.json"
_FILE_ANOMALIES = "bgp_anomalies.json"


class BgpHistoryStore:
    """
    In-memory BGP history store with optional JSON-file persistence.

    Ephemeral (no disk):
        store = BgpHistoryStore()

    Persistent (survives pod restart):
        store = BgpHistoryStore(persist_dir=Path("/data/bgp_history"))
        store.load_from_disk()   # call once at server startup
    """

    def __init__(self, persist_dir: Path | None = None) -> None:
        # ── Four in-memory tables ─────────────────────────────────────────────
        self.route_snapshots: list[BgpRouteSnapshotRow]    = []
        self.peer_summaries:  list[BgpPeerRouteSummaryRow] = []
        self.route_events:    list[BgpRouteEventRow]       = []
        self.anomalies:       list[BgpAnomalyRow]          = []

        # ── Optional persistence directory ────────────────────────────────────
        # When set, every write operation flushes all four tables to disk.
        self.persist_dir = persist_dir

    # =========================================================================
    # Startup — reload persisted state
    # =========================================================================

    def load_from_disk(self) -> None:
        """
        Read all four JSON files from persist_dir and populate the in-memory
        tables. Safe to call when files do not yet exist (first boot returns
        empty tables). Call once at server startup before serving requests.
        """
        if self.persist_dir is None:
            return

        self._load_snapshots()
        self._load_summaries()
        self._load_events()
        self._load_anomalies()

        LOG.info(
            "Loaded from disk — snapshots=%d summaries=%d events=%d anomalies=%d",
            len(self.route_snapshots),
            len(self.peer_summaries),
            len(self.route_events),
            len(self.anomalies),
        )

    def _load_snapshots(self) -> None:
        path = self.persist_dir / _FILE_SNAPSHOTS
        if not path.exists():
            return
        try:
            for raw in json.loads(path.read_text(encoding="utf-8")):
                self.route_snapshots.append(BgpRouteSnapshotRow(**raw))
        except Exception as exc:
            LOG.error("Failed to load %s: %s", path, exc)

    def _load_summaries(self) -> None:
        path = self.persist_dir / _FILE_SUMMARIES
        if not path.exists():
            return
        try:
            for raw in json.loads(path.read_text(encoding="utf-8")):
                self.peer_summaries.append(BgpPeerRouteSummaryRow(**raw))
        except Exception as exc:
            LOG.error("Failed to load %s: %s", path, exc)

    def _load_events(self) -> None:
        path = self.persist_dir / _FILE_EVENTS
        if not path.exists():
            return
        try:
            for raw in json.loads(path.read_text(encoding="utf-8")):
                self.route_events.append(BgpRouteEventRow(**raw))
        except Exception as exc:
            LOG.error("Failed to load %s: %s", path, exc)

    def _load_anomalies(self) -> None:
        path = self.persist_dir / _FILE_ANOMALIES
        if not path.exists():
            return
        try:
            for raw in json.loads(path.read_text(encoding="utf-8")):
                self.anomalies.append(BgpAnomalyRow(**raw))
        except Exception as exc:
            LOG.error("Failed to load %s: %s", path, exc)

    # =========================================================================
    # Write operations — append rows then flush to disk
    # =========================================================================

    def store_route_snapshot_rows(self, routes: list[BgpRouteRecord]) -> None:
        """Append one full route snapshot (all prefixes at one timestamp)."""
        for route in routes:
            self.route_snapshots.append(
                BgpRouteSnapshotRow(
                    ts=route.timestamp_ms,
                    device=route.device,
                    network_instance=route.network_instance,
                    peer=route.peer,
                    direction=route.direction,
                    afi_safi=route.afi_safi,
                    prefix=route.prefix,
                    next_hop=route.next_hop,
                    as_path=route.as_path,
                    local_pref=route.local_pref,
                    med=route.med,
                    communities=route.communities,
                    origin=route.origin,
                    best_path=route.best_path,
                    validation_state=route.validation_state,
                    region=route.region,
                    pop=route.pop,
                    fabric=route.fabric,
                )
            )
        LOG.info("Stored %d route snapshot rows", len(routes))
        self._persist()

    def store_peer_summary_rows(self, summaries: list[BgpPeerRouteSummary]) -> None:
        """Append aggregate received / advertised counts for each peer."""
        for summary in summaries:
            self.peer_summaries.append(
                BgpPeerRouteSummaryRow(
                    ts=summary.timestamp_ms,
                    device=summary.device,
                    network_instance=summary.network_instance,
                    peer=summary.peer,
                    afi_safi=summary.afi_safi,
                    received_prefix_count=summary.received_prefix_count,
                    advertised_prefix_count=summary.advertised_prefix_count,
                    region=summary.region,
                    pop=summary.pop,
                    fabric=summary.fabric,
                )
            )
        LOG.info("Stored %d peer summary rows", len(summaries))
        self._persist()

    def store_route_event_rows(self, events: list[BgpRouteEvent]) -> None:
        """Append route_added / route_removed / route_changed events."""
        for event in events:
            self.route_events.append(
                BgpRouteEventRow(
                    ts=event.timestamp_ms,
                    device=event.device,
                    network_instance=event.network_instance,
                    peer=event.peer,
                    direction=event.direction,
                    afi_safi=event.afi_safi,
                    prefix=event.prefix,
                    event_type=event.event_type,
                    details=event.details,
                )
            )
        LOG.info("Stored %d route event rows", len(events))
        self._persist()

    def store_anomaly_rows(self, anomalies: list[BgpAnomaly]) -> None:
        """Append classified anomaly records from BgpAnomalyDetector."""
        for anomaly in anomalies:
            self.anomalies.append(
                BgpAnomalyRow(
                    ts=anomaly.timestamp_ms,
                    device=anomaly.device,
                    network_instance=anomaly.network_instance,
                    peer=anomaly.peer,
                    afi_safi=anomaly.afi_safi,
                    anomaly_type=anomaly.anomaly_type,
                    severity=anomaly.severity,
                    blast_radius=anomaly.blast_radius,
                    details=anomaly.details,
                )
            )
        LOG.info("Stored %d anomaly rows", len(anomalies))
        self._persist()

    # =========================================================================
    # Persistence — flush all tables to disk
    # =========================================================================

    def _persist(self) -> None:
        """
        Write all four tables to JSON files in persist_dir.

        Called automatically after every write. A no-op when persist_dir
        is None. Write failures are logged but never propagate — a disk
        error must not break the in-memory serving path.
        """
        if self.persist_dir is None:
            return

        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            _write_json(self.persist_dir / _FILE_SNAPSHOTS,
                        [asdict(r) for r in self.route_snapshots])
            _write_json(self.persist_dir / _FILE_SUMMARIES,
                        [asdict(r) for r in self.peer_summaries])
            _write_json(self.persist_dir / _FILE_EVENTS,
                        [asdict(r) for r in self.route_events])
            _write_json(self.persist_dir / _FILE_ANOMALIES,
                        [asdict(r) for r in self.anomalies])
        except Exception as exc:
            LOG.error("Failed to persist BGP history to disk: %s", exc)

    # =========================================================================
    # Query operations — time-windowed reads
    # =========================================================================

    def routes_at_or_before(
        self,
        timestamp_ms: int,
        peer: str | None = None,
        direction: str | None = None,
        afi_safi: str | None = None,
    ) -> list[BgpRouteSnapshotRow]:
        """
        Return rows from the nearest snapshot at or before timestamp_ms.

        This is a point-in-time read: only rows from the single nearest
        snapshot timestamp are returned, not all rows up to the cutoff.
        """
        candidate_ts_values = [
            row.ts for row in self.route_snapshots if row.ts <= timestamp_ms
        ]
        if not candidate_ts_values:
            return []

        snapshot_ts = max(candidate_ts_values)

        rows = [
            row for row in self.route_snapshots
            if row.ts == snapshot_ts
            and (peer      is None or row.peer      == peer)
            and (direction is None or row.direction == direction)
            and (afi_safi  is None or row.afi_safi  == afi_safi)
        ]

        return sorted(rows, key=lambda r: (
            r.device, r.network_instance, r.peer,
            r.direction, r.afi_safi, r.prefix,
        ))

    def route_events_between(
        self,
        start_ts: int,
        end_ts: int,
        peer: str | None = None,
        direction: str | None = None,
        afi_safi: str | None = None,
        event_type: str | None = None,
    ) -> list[BgpRouteEventRow]:
        """
        Return all route events in the closed interval [start_ts, end_ts].

        event_type is one of: route_added, route_removed, route_changed.
        Pass None to receive all event types.
        """
        rows = [
            row for row in self.route_events
            if start_ts <= row.ts <= end_ts
            and (peer       is None or row.peer       == peer)
            and (direction  is None or row.direction  == direction)
            and (afi_safi   is None or row.afi_safi   == afi_safi)
            and (event_type is None or row.event_type == event_type)
        ]

        return sorted(rows, key=lambda r: (
            r.ts, r.device, r.peer, r.direction, r.prefix,
        ))

    def peer_summaries_at_or_before(
        self,
        timestamp_ms: int,
        peer: str | None = None,
        afi_safi: str | None = None,
    ) -> list[BgpPeerRouteSummaryRow]:
        """
        Return the most recent summary row per peer key, as of timestamp_ms.

        Unlike route_snapshots, peer summaries accumulate over time. We
        return the latest row per (device, ni, peer, afi_safi) key.
        """
        latest_by_key: dict[str, BgpPeerRouteSummaryRow] = {}

        for row in self.peer_summaries:
            if row.ts > timestamp_ms:
                continue
            if peer     is not None and row.peer     != peer:
                continue
            if afi_safi is not None and row.afi_safi != afi_safi:
                continue

            key = row.peer_key()
            existing = latest_by_key.get(key)
            if existing is None or row.ts > existing.ts:
                latest_by_key[key] = row

        return sorted(latest_by_key.values(), key=lambda r: (
            r.device, r.network_instance, r.peer, r.afi_safi,
        ))

    def anomalies_between(
        self,
        start_ts: int,
        end_ts: int,
        peer: str | None = None,
        anomaly_type: str | None = None,
    ) -> list[BgpAnomalyRow]:
        """Return classified anomalies in [start_ts, end_ts]."""
        rows = [
            row for row in self.anomalies
            if start_ts <= row.ts <= end_ts
            and (peer         is None or row.peer         == peer)
            and (anomaly_type is None or row.anomaly_type == anomaly_type)
        ]

        return sorted(rows, key=lambda r: (
            r.ts, r.device, r.peer, r.anomaly_type,
        ))

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def write_json_artifacts(self, output_dir: Path) -> None:
        """
        Dump all four tables to JSON files in output_dir.

        Used by demo scripts and integration tests. Not part of the
        normal serving path — use persist_dir for operational persistence.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename, payload in (
            (_FILE_SNAPSHOTS, [asdict(r) for r in self.route_snapshots]),
            (_FILE_SUMMARIES, [asdict(r) for r in self.peer_summaries]),
            (_FILE_EVENTS,    [asdict(r) for r in self.route_events]),
            (_FILE_ANOMALIES, [asdict(r) for r in self.anomalies]),
        ):
            path = output_dir / filename
            _write_json(path, payload)
            LOG.info("Wrote artifact to %s", path)


# ── Module-level helper ───────────────────────────────────────────────────────

def _write_json(path: Path, payload: list[Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
