from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from internal.knowledge.orchestration.evpn_analysis_service import (
    EVPNAnalysisRequest,
    EVPNAnalysisService,
)


class EVPNAnalyzeBody(BaseModel):
    question: str = Field(..., min_length=1)
    vendor: str = Field(..., min_length=1)
    scenario: str = Field(..., min_length=1)

    capability: str | None = None
    nos_family: str | None = None
    feature: str | None = None

    device: str | None = None
    fabric: str | None = None
    site: str | None = None
    pod: str | None = None
    vrf: str | None = None
    vni: int | None = None
    mac: str | None = None
    vtep: str | None = None
    incident_id: str | None = None
    timestamp_utc: str | None = None

    limit: int = Field(default=5, ge=1, le=20)


class EVPNAnalyzeResponse(BaseModel):
    ok: bool
    result: dict[str, Any]


@lru_cache(maxsize=1)
def get_service() -> EVPNAnalysisService:
    lattice_root = os.environ.get("LATTICE_ROOT", "").strip()
    if not lattice_root:
        raise RuntimeError("LATTICE_ROOT must be set")

    coverage_summary_path = os.path.join(
        lattice_root,
        "data",
        "generated",
        "schema",
        "evpn_vxlan_coverage_summary.json",
    )
    policy_dir = os.path.join(
        lattice_root,
        "internal",
        "knowledge",
        "policy",
        "evpn",
    )

    return EVPNAnalysisService(
        coverage_summary_path=coverage_summary_path,
        policy_dir=policy_dir,
    )


app = FastAPI(title="EVPN Analysis Service", version="1.0.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/evpn/analyze", response_model=EVPNAnalyzeResponse)
def analyze_evpn(body: EVPNAnalyzeBody) -> EVPNAnalyzeResponse:
    try:
        service = get_service()
        request = EVPNAnalysisRequest(
            question=body.question,
            vendor=body.vendor,
            nos_family=body.nos_family,
            scenario=body.scenario,
            capability=body.capability,
            feature=body.feature,
            device=body.device,
            fabric=body.fabric,
            site=body.site,
            pod=body.pod,
            vrf=body.vrf,
            vni=body.vni,
            mac=body.mac,
            vtep=body.vtep,
            incident_id=body.incident_id,
            timestamp_utc=body.timestamp_utc,
            limit=body.limit,
        )
        result = service.analyze(request)
        return EVPNAnalyzeResponse(ok=True, result=result.to_dict())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
