from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer


@dataclass
class IngestConfig:
    repo_root: Path
    domain_name: str = "evpn_vxlan"
    collection_name: str = "nre_evpn_vxlan_docs"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_vector_size: int = 384
    distance: qmodels.Distance = qmodels.Distance.COSINE
    create_collection_if_missing: bool = True
    batch_size: int = 32


class IngestError(Exception):
    pass


def load_yaml(path: Path) -> Any:
    if not path.exists():
        raise IngestError(f"Missing YAML file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now_utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_list(value: Any, field_name: str, chunk_id: str) -> list[Any]:
    if not isinstance(value, list):
        raise IngestError(f"{chunk_id}: field '{field_name}' must be a list")
    return value


def ensure_dict(value: Any, field_name: str, chunk_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IngestError(f"{chunk_id}: field '{field_name}' must be an object")
    return value


def ensure_str(value: Any, field_name: str, chunk_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestError(f"{chunk_id}: field '{field_name}' must be a non empty string")
    return value


def ensure_int(value: Any, field_name: str, chunk_id: str) -> int:
    if not isinstance(value, int):
        raise IngestError(f"{chunk_id}: field '{field_name}' must be an integer")
    return value


def ensure_float(value: Any, field_name: str, chunk_id: str) -> float:
    if not isinstance(value, (int, float)):
        raise IngestError(f"{chunk_id}: field '{field_name}' must be a number")
    return float(value)


def ensure_bool(value: Any, field_name: str, chunk_id: str) -> bool:
    if not isinstance(value, bool):
        raise IngestError(f"{chunk_id}: field '{field_name}' must be a boolean")
    return value


def load_documents_map(documents_path: Path) -> dict[str, dict[str, Any]]:
    docs = load_yaml(documents_path)
    if not isinstance(docs, list):
        raise IngestError(f"documents.yaml must contain a list: {documents_path}")

    out: dict[str, dict[str, Any]] = {}
    for doc in docs:
        if not isinstance(doc, dict):
            raise IngestError("Each document entry must be an object")
        doc_id = doc.get("document_id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise IngestError("Every document must have a non empty document_id")
        if doc_id in out:
            raise IngestError(f"Duplicate document_id found: {doc_id}")
        out[doc_id] = doc
    return out


def load_controlled_vocab(tags_path: Path, scenarios_path: Path) -> dict[str, set[str]]:
    tags = load_yaml(tags_path) or {}
    scenarios = load_yaml(scenarios_path) or []

    allowed: dict[str, set[str]] = {
        "vendors": set(tags.get("vendors", []) or []),
        "nos_families": set(tags.get("nos_families", []) or []),
        "source_types": set(tags.get("source_types", []) or []),
        "roles": set(tags.get("roles", []) or []),
        "domains": set(tags.get("domains", []) or []),
        "features": set(tags.get("features", []) or []),
        "capabilities": set(tags.get("capabilities", []) or []),
        "scenarios": set(tags.get("scenarios", []) or []),
    }

    scenario_names = set()
    for item in scenarios:
        if isinstance(item, dict) and isinstance(item.get("scenario"), str):
            scenario_names.add(item["scenario"])
    if scenario_names:
        allowed["scenarios"] = allowed["scenarios"].union(scenario_names)

    return allowed


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
            if not isinstance(item, dict):
                raise IngestError(f"{path}:{line_no} each JSONL row must be an object")
            yield item


def validate_membership(values: list[Any], allowed: set[str], field_name: str, chunk_id: str) -> None:
    for value in values:
        if not isinstance(value, str):
            raise IngestError(f"{chunk_id}: all values in '{field_name}' must be strings")
        if allowed and value not in allowed:
            raise IngestError(f"{chunk_id}: invalid value '{value}' in '{field_name}'")


def validate_chunk(
    chunk: dict[str, Any],
    doc: dict[str, Any],
    allowed: dict[str, set[str]],
) -> dict[str, Any]:
    chunk_id = ensure_str(chunk.get("chunk_id"), "chunk_id", "<unknown>")
    document_id = ensure_str(chunk.get("document_id"), "document_id", chunk_id)

    if document_id != doc["document_id"]:
        raise IngestError(
            f"{chunk_id}: document_id '{document_id}' does not match registry entry '{doc['document_id']}'"
        )

    domain = ensure_str(chunk.get("domain"), "domain", chunk_id)
    vendor = ensure_str(chunk.get("vendor"), "vendor", chunk_id)
    nos_family = ensure_str(chunk.get("nos_family"), "nos_family", chunk_id)
    source_type = ensure_str(chunk.get("source_type"), "source_type", chunk_id)
    priority = ensure_str(chunk.get("priority"), "priority", chunk_id)
    text = ensure_str(chunk.get("text"), "text", chunk_id)
    chunk_type = ensure_str(chunk.get("chunk_type"), "chunk_type", chunk_id)

    if domain != doc["domain"]:
        raise IngestError(f"{chunk_id}: domain '{domain}' does not match registry '{doc['domain']}'")
    if vendor != doc["vendor"]:
        raise IngestError(f"{chunk_id}: vendor '{vendor}' does not match registry '{doc['vendor']}'")
    if nos_family != doc["nos_family"]:
        raise IngestError(f"{chunk_id}: nos_family '{nos_family}' does not match registry '{doc['nos_family']}'")
    if source_type != doc["source_type"]:
        raise IngestError(f"{chunk_id}: source_type '{source_type}' does not match registry '{doc['source_type']}'")

    page_start = ensure_int(chunk.get("page_start"), "page_start", chunk_id)
    page_end = ensure_int(chunk.get("page_end"), "page_end", chunk_id)
    if page_end < page_start:
        raise IngestError(f"{chunk_id}: page_end cannot be less than page_start")

    role = ensure_list(chunk.get("role"), "role", chunk_id)
    validate_membership(role, allowed["roles"], "role", chunk_id)

    tags = ensure_dict(chunk.get("tags"), "tags", chunk_id)
    features = ensure_list(tags.get("features", []), "tags.features", chunk_id)
    scenarios = ensure_list(tags.get("scenarios", []), "tags.scenarios", chunk_id)
    capabilities = ensure_list(tags.get("capabilities", []), "tags.capabilities", chunk_id)
    route_types = ensure_list(tags.get("route_types", []), "tags.route_types", chunk_id)
    topology_roles = ensure_list(tags.get("topology_roles", []), "tags.topology_roles", chunk_id)

    validate_membership(features, allowed["features"], "tags.features", chunk_id)
    validate_membership(scenarios, allowed["scenarios"], "tags.scenarios", chunk_id)
    validate_membership(capabilities, allowed["capabilities"], "tags.capabilities", chunk_id)

    retrieval_weight = ensure_dict(chunk.get("retrieval_weight"), "retrieval_weight", chunk_id)
    ensure_float(retrieval_weight.get("semantic"), "retrieval_weight.semantic", chunk_id)
    ensure_float(retrieval_weight.get("keyword"), "retrieval_weight.keyword", chunk_id)
    ensure_float(retrieval_weight.get("trust"), "retrieval_weight.trust", chunk_id)
    ensure_float(retrieval_weight.get("priority"), "retrieval_weight.priority", chunk_id)

    evidence_quality = ensure_dict(chunk.get("evidence_quality"), "evidence_quality", chunk_id)
    ensure_bool(evidence_quality.get("packet_level"), "evidence_quality.packet_level", chunk_id)
    ensure_bool(evidence_quality.get("config_level"), "evidence_quality.config_level", chunk_id)
    ensure_bool(evidence_quality.get("design_level"), "evidence_quality.design_level", chunk_id)
    ensure_bool(evidence_quality.get("troubleshooting_level"), "evidence_quality.troubleshooting_level", chunk_id)

    use_constraints = ensure_dict(chunk.get("use_constraints"), "use_constraints", chunk_id)
    ensure_bool(use_constraints.get("safe_for_explanation"), "use_constraints.safe_for_explanation", chunk_id)
    ensure_bool(use_constraints.get("safe_for_diagnosis"), "use_constraints.safe_for_diagnosis", chunk_id)
    ensure_bool(use_constraints.get("safe_for_remediation"), "use_constraints.safe_for_remediation", chunk_id)
    ensure_bool(use_constraints.get("safe_for_capability_claim"), "use_constraints.safe_for_capability_claim", chunk_id)

    # Optional strings
    if "section_title" in chunk and chunk["section_title"] is not None:
        ensure_str(chunk["section_title"], "section_title", chunk_id)
    if "subsection_title" in chunk and chunk["subsection_title"] is not None:
        ensure_str(chunk["subsection_title"], "subsection_title", chunk_id)

    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "domain": domain,
        "vendor": vendor,
        "nos_family": nos_family,
        "source_type": source_type,
        "priority": priority,
        "role": role,
        "chunk_type": chunk_type,
        "section_title": chunk.get("section_title"),
        "subsection_title": chunk.get("subsection_title"),
        "page_start": page_start,
        "page_end": page_end,
        "text": text,
        "tags": {
            "features": features,
            "scenarios": scenarios,
            "capabilities": capabilities,
            "route_types": route_types,
            "topology_roles": topology_roles,
        },
        "retrieval_weight": retrieval_weight,
        "evidence_quality": evidence_quality,
        "use_constraints": use_constraints,
    }


def build_payload(
    validated_chunk: dict[str, Any],
    doc: dict[str, Any],
    pdf_path: Path,
    chunk_path: Path,
) -> dict[str, Any]:
    payload = {
        "chunk_id": validated_chunk["chunk_id"],
        "document_id": validated_chunk["document_id"],
        "domain": validated_chunk["domain"],
        "vendor": validated_chunk["vendor"],
        "nos_family": validated_chunk["nos_family"],
        "source_type": validated_chunk["source_type"],
        "priority": validated_chunk["priority"],
        "role": validated_chunk["role"],
        "chunk_type": validated_chunk["chunk_type"],
        "section_title": validated_chunk["section_title"],
        "subsection_title": validated_chunk["subsection_title"],
        "page_start": validated_chunk["page_start"],
        "page_end": validated_chunk["page_end"],
        "text": validated_chunk["text"],
        "tags": validated_chunk["tags"],
        "retrieval_weight": validated_chunk["retrieval_weight"],
        "evidence_quality": validated_chunk["evidence_quality"],
        "use_constraints": validated_chunk["use_constraints"],
        "filename": doc["filename"],
        "document_title": doc.get("document_title"),
        "pdf_path": str(pdf_path),
        "chunk_source_path": str(chunk_path),
    }

    # Copy selected document level metadata into payload for easier filtering later
    for optional_key in (
        "platform_family",
        "authoritative_for",
        "advisory_for",
        "not_authoritative_for",
        "retrieval_hints",
        "lifecycle",
        "trust_level",
    ):
        if optional_key in doc:
            payload[optional_key] = doc[optional_key]

    return payload


def ensure_collection(client: QdrantClient, config: IngestConfig) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if config.collection_name in existing:
        return

    if not config.create_collection_if_missing:
        raise IngestError(f"Collection does not exist: {config.collection_name}")

    client.create_collection(
        collection_name=config.collection_name,
        vectors_config=qmodels.VectorParams(
            size=config.qdrant_vector_size,
            distance=config.distance,
        ),
    )


def chunked(seq: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def point_id_from_chunk_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"lattice:{chunk_id}"))


def ingest(config: IngestConfig) -> Path:
    base = config.repo_root / "internal" / "knowledge" / "domains" / config.domain_name
    registry_dir = base / "registry"
    chunks_dir = base / "chunks" / "jsonl"
    manifests_dir = base / "manifests" / "ingest_runs"

    manifests_dir.mkdir(parents=True, exist_ok=True)

    documents_map = load_documents_map(registry_dir / "documents.yaml")
    allowed = load_controlled_vocab(registry_dir / "tags.yaml", registry_dir / "scenarios.yaml")

    embedder = SentenceTransformer(config.embedding_model_name)
    client = QdrantClient(url=config.qdrant_url, check_compatibility=False)
    ensure_collection(client, config)

    run_id = now_utc_stamp()
    run_manifest: dict[str, Any] = {
        "run_id": run_id,
        "domain": config.domain_name,
        "collection_name": config.collection_name,
        "embedding_model_name": config.embedding_model_name,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "documents": [],
    }

    all_points: list[qmodels.PointStruct] = []

    for doc_id, doc in documents_map.items():
        vendor = doc["vendor"]
        pdf_path = base / "raw" / vendor / doc["filename"]
        chunk_path = chunks_dir / f"{doc_id}.jsonl"

        if not pdf_path.exists():
            raise IngestError(f"Missing PDF for {doc_id}: {pdf_path}")
        if not chunk_path.exists():
            raise IngestError(f"Missing JSONL for {doc_id}: {chunk_path}")

        file_sha = sha256_file(pdf_path)
        raw_chunks = list(iter_jsonl(chunk_path))
        validated_chunks = [validate_chunk(chunk, doc, allowed) for chunk in raw_chunks]
        texts = [c["text"] for c in validated_chunks]

        vectors = embedder.encode(texts, normalize_embeddings=True).tolist()

        doc_points: list[qmodels.PointStruct] = []
        for chunk_obj, vector in zip(validated_chunks, vectors):
            payload = build_payload(chunk_obj, doc, pdf_path, chunk_path)
            point = qmodels.PointStruct(
                id=point_id_from_chunk_id(chunk_obj["chunk_id"]),
                vector=vector,
                payload=payload,
            )
            doc_points.append(point)

        all_points.extend(doc_points)

        run_manifest["documents"].append(
            {
                "document_id": doc_id,
                "filename": doc["filename"],
                "vendor": vendor,
                "pdf_path": str(pdf_path),
                "chunk_path": str(chunk_path),
                "pdf_sha256": file_sha,
                "chunks_written": len(doc_points),
                "status": "success",
            }
        )

    for batch in chunked(all_points, config.batch_size):
        client.upsert(collection_name=config.collection_name, points=batch)

    run_manifest["total_documents"] = len(run_manifest["documents"])
    run_manifest["total_chunks"] = len(all_points)
    run_manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    run_manifest["status"] = "success"

    manifest_path = manifests_dir / f"{run_id}.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(run_manifest, fh, indent=2)

    return manifest_path


def main() -> None:
    repo_root = Path.cwd()
    while repo_root != repo_root.parent and not (repo_root / "internal").exists():
        repo_root = repo_root.parent

    if not (repo_root / "internal").exists():
        raise IngestError("Could not find repo root containing 'internal' directory")

    config = IngestConfig(repo_root=repo_root)
    manifest_path = ingest(config)
    print(f"WROTE MANIFEST: {manifest_path}")


if __name__ == "__main__":
    main()
