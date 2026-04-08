from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer


@dataclass
class RetrieverConfig:
    qdrant_url: str = "http://127.0.0.1:6333"
    collection_name: str = "nre_evpn_vxlan_docs"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    score_threshold: float | None = None
    default_limit: int = 5


@dataclass
class RetrievalRequest:
    query: str
    domain: str = "evpn_vxlan"
    vendor: str | None = None
    nos_family: str | None = None
    scenario: str | None = None
    capability: str | None = None
    role: str | None = None
    feature: str | None = None
    safe_for_diagnosis: bool | None = True
    safe_for_explanation: bool | None = None
    safe_for_remediation: bool | None = None
    safe_for_capability_claim: bool | None = None
    limit: int = 5


@dataclass
class RetrievedChunk:
    score: float
    chunk_id: str
    document_id: str
    vendor: str
    nos_family: str
    source_type: str
    section_title: str | None
    subsection_title: str | None
    page_start: int | None
    page_end: int | None
    text: str
    payload: dict[str, Any] = field(default_factory=dict)


class EvpnVxlanRetriever:
    def __init__(self, config: RetrieverConfig | None = None) -> None:
        self.config = config or RetrieverConfig()
        self.client = QdrantClient(
            url=self.config.qdrant_url,
        )
        self.embedder = SentenceTransformer(self.config.embedding_model_name)

    def _make_filter(self, req: RetrievalRequest) -> qmodels.Filter:
        must: list[qmodels.FieldCondition] = [
            qmodels.FieldCondition(
                key="domain",
                match=qmodels.MatchValue(value=req.domain),
            )
        ]

        if req.vendor:
            must.append(
                qmodels.FieldCondition(
                    key="vendor",
                    match=qmodels.MatchValue(value=req.vendor),
                )
            )

        if req.nos_family:
            must.append(
                qmodels.FieldCondition(
                    key="nos_family",
                    match=qmodels.MatchValue(value=req.nos_family),
                )
            )

        if req.role:
            must.append(
                qmodels.FieldCondition(
                    key="role[]",
                    match=qmodels.MatchValue(value=req.role),
                )
            )

        if req.scenario:
            must.append(
                qmodels.FieldCondition(
                    key="tags.scenarios[]",
                    match=qmodels.MatchValue(value=req.scenario),
                )
            )

        if req.capability:
            must.append(
                qmodels.FieldCondition(
                    key="tags.capabilities[]",
                    match=qmodels.MatchValue(value=req.capability),
                )
            )

        if req.feature:
            must.append(
                qmodels.FieldCondition(
                    key="tags.features[]",
                    match=qmodels.MatchValue(value=req.feature),
                )
            )

        if req.safe_for_diagnosis is not None:
            must.append(
                qmodels.FieldCondition(
                    key="use_constraints.safe_for_diagnosis",
                    match=qmodels.MatchValue(value=req.safe_for_diagnosis),
                )
            )

        if req.safe_for_explanation is not None:
            must.append(
                qmodels.FieldCondition(
                    key="use_constraints.safe_for_explanation",
                    match=qmodels.MatchValue(value=req.safe_for_explanation),
                )
            )

        if req.safe_for_remediation is not None:
            must.append(
                qmodels.FieldCondition(
                    key="use_constraints.safe_for_remediation",
                    match=qmodels.MatchValue(value=req.safe_for_remediation),
                )
            )

        if req.safe_for_capability_claim is not None:
            must.append(
                qmodels.FieldCondition(
                    key="use_constraints.safe_for_capability_claim",
                    match=qmodels.MatchValue(value=req.safe_for_capability_claim),
                )
            )

        return qmodels.Filter(must=must)

    def retrieve(self, req: RetrievalRequest) -> list[RetrievedChunk]:
        query_vector = self.embedder.encode(req.query, normalize_embeddings=True).tolist()
        query_filter = self._make_filter(req)
        
        points = self.client.search(
            collection_name=self.config.collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=req.limit or self.config.default_limit,
            score_threshold=self.config.score_threshold,
            with_payload=True,
            with_vectors=False,
        )

        results: list[RetrievedChunk] = []
        for point in points:
            payload = point.payload or {}
            results.append(
                RetrievedChunk(
                    score=float(point.score),
                    chunk_id=str(payload.get("chunk_id", "")),
                    document_id=str(payload.get("document_id", "")),
                    vendor=str(payload.get("vendor", "")),
                    nos_family=str(payload.get("nos_family", "")),
                    source_type=str(payload.get("source_type", "")),
                    section_title=payload.get("section_title"),
                    subsection_title=payload.get("subsection_title"),
                    page_start=payload.get("page_start"),
                    page_end=payload.get("page_end"),
                    text=str(payload.get("text", "")),
                    payload=payload,
                )
            )

        return results


def pretty_print_results(results: list[RetrievedChunk]) -> None:
    if not results:
        print("No results found")
        return

    for idx, item in enumerate(results, start=1):
        print("=" * 100)
        print(f"Result {idx}")
        print(f"Score        : {item.score:.4f}")
        print(f"Document     : {item.document_id}")
        print(f"Vendor       : {item.vendor}")
        print(f"NOS          : {item.nos_family}")
        print(f"Source type  : {item.source_type}")
        print(f"Section      : {item.section_title}")
        print(f"Subsection   : {item.subsection_title}")
        print(f"Pages        : {item.page_start} to {item.page_end}")
        print("Text:")
        print(item.text)
        print()


if __name__ == "__main__":
    retriever = EvpnVxlanRetriever()

    req = RetrievalRequest(
        query="How does Arista EVPN multihoming compare MLAG and all active behavior?",
        vendor="arista",
        scenario="multihoming_design_selection",
        role="reasoning_primary",
        safe_for_diagnosis=True,
        limit=5,
    )

    results = retriever.retrieve(req)
    pretty_print_results(results)
