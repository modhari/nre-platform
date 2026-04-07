"""
rag_context.py — BGP RAG context capability for mcp_server.

Responsibilities:
  - Accept vendor, device, and anomaly_type from the agent.
  - Query Qdrant for the most relevant BGP troubleshooting chunks.
  - Return a list of text excerpts the agent embeds in its reasoning
    context before deciding on a remediation action.

Collection strategy:
  Primary:   nre_bgp_docs          BGP-specific troubleshooting knowledge
  Fallback:  nre_evpn_vxlan_docs   EVPN/BGP overlap docs (already ingested)

When neither collection exists this capability returns an empty list
gracefully. The agent proceeds without RAG context rather than failing.
No embedding model is loaded here — Qdrant scroll with metadata filters
is precise enough for the vendor + anomaly_type query pattern.

Environment variables:
  QDRANT_URL              default: http://qdrant:6333
  BGP_RAG_COLLECTION      default: nre_bgp_docs
  BGP_RAG_FALLBACK_COLL   default: nre_evpn_vxlan_docs
  BGP_RAG_TOP_K           number of chunks to return, default: 4
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


# ── Qdrant configuration ──────────────────────────────────────────────────────

def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")

def _bgp_collection() -> str:
    return os.getenv("BGP_RAG_COLLECTION", "nre_bgp_docs")

def _fallback_collection() -> str:
    return os.getenv("BGP_RAG_FALLBACK_COLL", "nre_evpn_vxlan_docs")

def _top_k() -> int:
    return int(os.getenv("BGP_RAG_TOP_K", "4"))


# ── Public capability handler ─────────────────────────────────────────────────

def bgp_rag_context(request: dict[str, Any]) -> dict[str, Any]:
    """
    MCP capability handler for method bgp.rag_context.

    Expected params:
      vendor        e.g. arista, juniper, cisco  (optional filter)
      anomaly_type  e.g. received_route_zero     (optional filter)
      device        device name for audit logging (optional)
      limit         override top-k               (optional)

    Returns:
      ok: true  with result.chunks list of {text, document_id, score}
      ok: false only on unrecoverable internal error
      Missing collection is NOT an error — returns empty chunks list.
    """
    request_id = request.get("request_id", "unknown")
    params     = request.get("params", {}) or {}

    vendor       = str(params.get("vendor",       "")) or None
    anomaly_type = str(params.get("anomaly_type", "")) or None
    limit        = int(params.get("limit", _top_k()))

    # ── Try primary BGP collection, then fall back to EVPN collection ─────────
    # The EVPN collection is already ingested and contains BGP-adjacent content
    # (BGP EVPN peer analysis, route-type semantics, etc.) that is useful until
    # the dedicated BGP collection is populated.
    for collection in (_bgp_collection(), _fallback_collection()):
        if not _collection_exists(collection):
            continue

        chunks = _scroll_by_filter(
            collection=collection,
            vendor=vendor,
            anomaly_type=anomaly_type,
            limit=limit,
        )

        return {
            "api_version": "v1",
            "request_id":  request_id,
            "ok":          True,
            "result": {
                "collection":  collection,
                "chunk_count": len(chunks),
                "chunks":      chunks,
            },
        }

    # ── Neither collection exists yet — return empty gracefully ───────────────
    return {
        "api_version": "v1",
        "request_id":  request_id,
        "ok":          True,
        "result": {
            "collection":  None,
            "chunk_count": 0,
            "chunks":      [],
            "note": (
                "BGP RAG collection not yet populated. "
                "Run the ingest pipeline to add BGP knowledge docs."
            ),
        },
    }


# ── Qdrant helpers ────────────────────────────────────────────────────────────

def _collection_exists(name: str) -> bool:
    """
    Return True if the named Qdrant collection exists and its status is green.

    Uses a short 3-second timeout — a slow or absent Qdrant should not
    block the MCP request for long.
    """
    try:
        url = f"{_qdrant_url()}/collections/{name}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("result", {}).get("status") == "green"
    except Exception:
        return False


def _scroll_by_filter(
    collection: str,
    vendor: str | None,
    anomaly_type: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Retrieve chunks from Qdrant using scroll (metadata filter, no vector).

    Scroll is used instead of semantic search because:
    - No embedding model is loaded inside mcp_server.
    - Filtering on vendor + anomaly_type is already specific enough to
      pull the right BGP troubleshooting sections.
    - The agent synthesises and re-ranks the returned text in its own
      context window.

    When a BGP-specific embedding model is added to mcp_server in future,
    replace this with a /collections/{name}/points/query call.
    """
    # ── Build Qdrant filter conditions ────────────────────────────────────────
    must: list[dict[str, Any]] = [
        {"key": "domain", "match": {"value": "bgp"}}
    ]

    if vendor:
        must.append({
            "key":   "vendor",
            "match": {"value": vendor},
        })

    if anomaly_type:
        # anomaly_type is stored as an array tag on BGP knowledge chunks
        must.append({
            "key":   "tags.anomaly_types[]",
            "match": {"value": anomaly_type},
        })

    payload = {
        "filter":       {"must": must},
        "limit":        limit,
        "with_payload": True,
        "with_vector":  False,
    }

    url  = f"{_qdrant_url()}/collections/{collection}/points/scroll"
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError:
        # Qdrant unreachable — return empty, do not crash the capability
        return []

    # ── Extract text and metadata from each returned point ────────────────────
    chunks: list[dict[str, Any]] = []

    for point in body.get("result", {}).get("points", []):
        p = point.get("payload", {})
        chunks.append({
            "chunk_id":           p.get("chunk_id", ""),
            "document_id":        p.get("document_id", ""),
            "vendor":             p.get("vendor", ""),
            "section_title":      p.get("section_title"),
            "text":               p.get("text", ""),
            "source_type":        p.get("source_type", ""),
            "safe_for_diagnosis": p.get(
                "use_constraints", {}
            ).get("safe_for_diagnosis", True),
        })

    return chunks
