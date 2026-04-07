"""
ingest_bgp.py — Ingest BGP troubleshooting knowledge into Qdrant.

Mirrors ingest_evpn_vxlan.py but skips the PDF source file requirement
since BGP knowledge chunks are authored directly as JSONL rather than
extracted from PDFs.

Usage:
    # From inside the lattice service directory:
    python -m internal.knowledge.ingest.ingest_bgp

    # Or with explicit Qdrant URL:
    QDRANT_URL=http://localhost:6333 python -m internal.knowledge.ingest.ingest_bgp

Environment variables:
    QDRANT_URL          default: http://127.0.0.1:6333
    BGP_COLLECTION      default: nre_bgp_docs
    EMBEDDING_MODEL     default: sentence-transformers/all-MiniLM-L6-v2
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class IngestConfig:
    repo_root: Path
    domain_name: str = "bgp"
    collection_name: str = "nre_bgp_docs"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_vector_size: int = 384
    distance: qmodels.Distance = qmodels.Distance.COSINE
    batch_size: int = 32


class IngestError(Exception):
    pass


# ── YAML / JSONL helpers ──────────────────────────────────────────────────────

def load_yaml(path: Path) -> Any:
    if not path.exists():
        raise IngestError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        raise IngestError(f"Missing JSONL file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IngestError(f"{path}:{line_no} invalid JSON: {exc}") from exc
            yield item


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"lattice:bgp:{chunk_id}"))


def chunked(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ── Collection setup ──────────────────────────────────────────────────────────

def ensure_collection(client: QdrantClient, config: IngestConfig) -> None:
    """Create the Qdrant collection if it does not already exist."""
    existing = {c.name for c in client.get_collections().collections}
    if config.collection_name in existing:
        print(f"[ingest_bgp] collection '{config.collection_name}' already exists — upserting")
        return

    client.create_collection(
        collection_name=config.collection_name,
        vectors_config=qmodels.VectorParams(
            size=config.qdrant_vector_size,
            distance=config.distance,
        ),
    )
    print(f"[ingest_bgp] created collection '{config.collection_name}'")


# ── Validation ────────────────────────────────────────────────────────────────

def load_documents_map(path: Path) -> dict[str, dict[str, Any]]:
    docs = load_yaml(path)
    if not isinstance(docs, list):
        raise IngestError("documents.yaml must be a list")
    out: dict[str, dict[str, Any]] = {}
    for doc in docs:
        doc_id = doc.get("document_id")
        if not doc_id:
            raise IngestError("Every document must have a document_id")
        out[doc_id] = doc
    return out


def validate_chunk(chunk: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Validate required fields and return the cleaned chunk."""
    chunk_id = chunk.get("chunk_id", "")
    required = ["chunk_id", "document_id", "domain", "vendor", "nos_family",
                "source_type", "priority", "role", "chunk_type", "text",
                "page_start", "page_end", "tags", "retrieval_weight",
                "evidence_quality", "use_constraints"]

    for field in required:
        if field not in chunk:
            raise IngestError(f"{chunk_id}: missing required field '{field}'")

    if chunk["document_id"] != doc["document_id"]:
        raise IngestError(
            f"{chunk_id}: document_id mismatch — "
            f"chunk has '{chunk['document_id']}', doc is '{doc['document_id']}'"
        )

    return chunk


# ── Main ingest ───────────────────────────────────────────────────────────────

def ingest(config: IngestConfig) -> Path:
    """
    Load all BGP knowledge chunks, embed them, and upsert into Qdrant.

    Returns the path to the manifest JSON written after a successful run.
    """
    base = config.repo_root / "internal" / "knowledge" / "domains" / config.domain_name
    registry_dir  = base / "registry"
    chunks_dir    = base / "chunks" / "jsonl"
    manifests_dir = base / "manifests" / "ingest_runs"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    # ── Load registry ─────────────────────────────────────────────────────────
    documents_map = load_documents_map(registry_dir / "documents.yaml")
    print(f"[ingest_bgp] loaded {len(documents_map)} documents from registry")

    # ── Load embedding model ──────────────────────────────────────────────────
    print(f"[ingest_bgp] loading embedding model: {config.embedding_model_name}")
    embedder = SentenceTransformer(config.embedding_model_name)

    # ── Connect to Qdrant ─────────────────────────────────────────────────────
    client = QdrantClient(url=config.qdrant_url, check_compatibility=False)
    ensure_collection(client, config)

    run_id = now_utc()
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "domain": config.domain_name,
        "collection_name": config.collection_name,
        "embedding_model_name": config.embedding_model_name,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "documents": [],
    }

    all_points: list[qmodels.PointStruct] = []

    # ── Process each document ─────────────────────────────────────────────────
    for doc_id, doc in documents_map.items():
        chunk_path = chunks_dir / f"{doc_id}.jsonl"

        if not chunk_path.exists():
            print(f"[ingest_bgp] WARNING: no JSONL for {doc_id} at {chunk_path} — skipping")
            continue

        raw_chunks     = list(iter_jsonl(chunk_path))
        validated      = [validate_chunk(c, doc) for c in raw_chunks]
        texts          = [c["text"] for c in validated]

        print(f"[ingest_bgp] embedding {len(texts)} chunks for {doc_id} ...")
        vectors = embedder.encode(texts, normalize_embeddings=True).tolist()

        doc_points: list[qmodels.PointStruct] = []
        for chunk, vector in zip(validated, vectors):
            payload = {**chunk, "document_title": doc.get("document_title", doc_id)}
            doc_points.append(
                qmodels.PointStruct(
                    id=point_id(chunk["chunk_id"]),
                    vector=vector,
                    payload=payload,
                )
            )

        all_points.extend(doc_points)
        manifest["documents"].append({
            "document_id":    doc_id,
            "chunk_path":     str(chunk_path),
            "chunks_written": len(doc_points),
            "status":         "success",
        })

    # ── Batch upsert into Qdrant ──────────────────────────────────────────────
    print(f"[ingest_bgp] upserting {len(all_points)} points into '{config.collection_name}'")
    for batch in chunked(all_points, config.batch_size):
        client.upsert(collection_name=config.collection_name, points=batch)

    # ── Write manifest ────────────────────────────────────────────────────────
    manifest["total_chunks"]      = len(all_points)
    manifest["total_documents"]   = len(manifest["documents"])
    manifest["finished_at_utc"]   = datetime.now(timezone.utc).isoformat()
    manifest["status"]            = "success"

    manifest_path = manifests_dir / f"{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[ingest_bgp] wrote manifest to {manifest_path}")

    return manifest_path


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    # Find repo root by walking up until we find the internal/ directory
    repo_root = Path.cwd()
    while repo_root != repo_root.parent and not (repo_root / "internal").exists():
        repo_root = repo_root.parent

    if not (repo_root / "internal").exists():
        raise IngestError("Could not find repo root containing 'internal/' directory")

    config = IngestConfig(
        repo_root=repo_root,
        qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        collection_name=os.getenv("BGP_COLLECTION", "nre_bgp_docs"),
        embedding_model_name=os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        ),
    )

    print(f"[ingest_bgp] starting BGP knowledge ingest")
    print(f"[ingest_bgp] qdrant_url={config.qdrant_url}")
    print(f"[ingest_bgp] collection={config.collection_name}")

    manifest_path = ingest(config)
    print(f"[ingest_bgp] SUCCESS — manifest: {manifest_path}")


if __name__ == "__main__":
    main()
