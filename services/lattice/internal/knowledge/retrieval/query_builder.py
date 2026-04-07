from __future__ import annotations

from dataclasses import dataclass

from internal.knowledge.retrieval.retriever import RetrievalRequest


@dataclass
class EvpnQuestion:
    question: str
    vendor: str | None = None
    nos_family: str | None = None
    scenario: str | None = None
    capability: str | None = None
    feature: str | None = None
    role: str | None = "reasoning_primary"
    limit: int = 5


def build_request(q: EvpnQuestion) -> RetrievalRequest:
    return RetrievalRequest(
        query=q.question,
        vendor=q.vendor,
        nos_family=q.nos_family,
        scenario=q.scenario,
        capability=q.capability,
        feature=q.feature,
        role=q.role,
        safe_for_diagnosis=True,
        limit=q.limit,
    )
