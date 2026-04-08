"""
loop.py — NRE agent control loop.

Two operating modes, selected via NRE_AGENT_MODE:

  bgp_diagnostics (default)
    Loads a BGP snapshot file, calls mcp_server for diagnosis, enriches
    the result with history queries, RAG context, and remediation
    planning, then publishes structured events to Kafka.

  scenario
    Cycles through synthetic fault scenarios against lattice for testing
    the approval gate and cooldown behaviour.

The loop runs forever with a configurable sleep interval between
iterations. All external calls go through agent.client — never direct
HTTP here.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from kafka import KafkaProducer

from agent.approval_state import (
    build_plan_state,
    plan_state_to_dict,
    summarize_plan_state,
)
from agent.approvals import (
    clear_approval_record,
    create_pending_approval,
    get_approval_record,
    summarize_approval_state,
    update_approval_status,
)
from agent.bgp_decision import (
    build_bgp_decision,
    decision_to_dict,
    summarize_bgp_decision,
)
from agent.client import (
    call_lattice,
    call_lattice_bgp_diagnostics,
    call_mcp_bgp_history_query,
    call_mcp_bgp_rag_context,
    call_mcp_bgp_remediation_plan,
)
from agent.execution_plan import (
    build_execution_plan,
    execution_plan_to_dict,
    summarize_execution_plan,
)
from agent.plan_memory import (
    classify_plan_change,
    compute_plan_fingerprint,
    write_plan_memory_record,
)
from agent.scenarios import get_next_scenario


# ── Approval cooldown state ───────────────────────────────────────────────────
# Keyed by incident_id or scenario name. After an approved action executes,
# the key is held in cooldown for NRE_AGENT_APPROVAL_COOLDOWN_SECONDS to
# prevent rapid re-execution on the next loop iteration.
_APPROVAL_COOLDOWN_UNTIL: dict[str, datetime] = {}


# ── Timestamps ────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Environment config helpers ────────────────────────────────────────────────

def _agent_mode() -> str:
    """
    Return the operating mode for this agent instance.

    bgp_diagnostics  process BGP snapshots and publish events (default)
    scenario         synthetic fault scenario loop for testing
    """
    return (
        os.environ.get("NRE_AGENT_MODE", "scenario").strip().lower()
        or "scenario"
    )

def _cooldown_seconds() -> int:
    """Seconds to hold a cooldown after an approved action runs."""
    return int(os.environ.get("NRE_AGENT_APPROVAL_COOLDOWN_SECONDS", "300"))

def _interval_seconds() -> int:
    """Seconds to sleep between loop iterations."""
    return int(os.environ.get("NRE_AGENT_INTERVAL_SECONDS", "30"))


# ── Approval cooldown helpers ─────────────────────────────────────────────────

def _set_cooldown(key: str) -> None:
    _APPROVAL_COOLDOWN_UNTIL[key] = _utc_now_dt() + timedelta(
        seconds=_cooldown_seconds()
    )

def _get_cooldown_remaining_seconds(key: str) -> int:
    expires = _APPROVAL_COOLDOWN_UNTIL.get(key)
    if expires is None:
        return 0
    return max(int((expires - _utc_now_dt()).total_seconds()), 0)

def _is_in_cooldown(key: str) -> bool:
    return _get_cooldown_remaining_seconds(key) > 0


# ── Kafka producer — lazy singleton ──────────────────────────────────────────

_kafka_producer = None

def get_kafka_producer() -> KafkaProducer | None:
    """
    Return a shared KafkaProducer when Kafka export is enabled.

    Enabled by NRE_AGENT_KAFKA_ENABLED=true. Falls back to None (silent
    no-op) when Kafka is unreachable or disabled. Kafka is observability
    infrastructure — its absence must never crash the agent loop.
    """
    global _kafka_producer

    if os.environ.get("NRE_AGENT_KAFKA_ENABLED", "false").lower() != "true":
        return None

    if _kafka_producer is not None:
        return _kafka_producer

    bootstrap = os.environ.get(
        "NRE_AGENT_KAFKA_BOOTSTRAP_SERVERS", ""
    ).strip()
    if not bootstrap:
        return None

    _kafka_producer = KafkaProducer(
        bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        acks="all",
        retries=3,
    )
    return _kafka_producer


def publish_kafka_event(topic: str, key: str, payload: dict) -> None:
    """
    Publish one event to Kafka.

    Failures are logged but never propagate — Kafka is observability
    infrastructure, not part of the decision or approval path.
    """
    producer = get_kafka_producer()
    if producer is None:
        return

    try:
        producer.send(topic, key=key, value=payload)
        producer.flush(timeout=2)
    except Exception as exc:
        print(
            f"[nre_agent] ts={_utc_now_iso()} kafka_publish_error "
            f"topic={topic} key={key} error={exc}",
            flush=True,
        )


# ── Approval gate helpers ─────────────────────────────────────────────────────

def _apply_simulated_approval_override(key: str) -> None:
    """
    Apply a test-mode approval override set via NRE_AGENT_APPROVAL_STATUS.

    In production this env var is empty. In CI or local dev it can be set
    to approved or rejected to exercise the gate without a real operator.
    """
    simulated = os.environ.get(
        "NRE_AGENT_APPROVAL_STATUS", ""
    ).strip().lower()
    if simulated not in {"approved", "rejected"}:
        return

    record = get_approval_record(key)
    if record is None or record.status == simulated:
        return

    updated = update_approval_status(key, simulated)
    print(
        f"[nre_agent] ts={_utc_now()} approval_key={key} "
        f"approval_transition={updated.status}",
        flush=True,
    )


def _precheck_approval_gate(key: str) -> bool:
    """
    Return True if the agent is allowed to proceed for this key.

    Gate states:
      no record        proceed (first time seeing this scenario)
      cooldown active  block   (recent action, wait before retrying)
      pending          block   (waiting for operator decision)
      rejected         block   (operator said no, suppress indefinitely)
      approved         clear record and proceed (operator said yes)
    """
    if _is_in_cooldown(key):
        remaining = _get_cooldown_remaining_seconds(key)
        print(
            f"[nre_agent] ts={_utc_now()} approval_key={key} "
            f"approval_gate=cooldown remaining_seconds={remaining}",
            flush=True,
        )
        return False

    record = get_approval_record(key)
    if record is None:
        return True

    if record.status == "pending":
        print(
            f"[nre_agent] ts={_utc_now()} approval_key={key} "
            f"approval_gate=hold approval_status=pending",
            flush=True,
        )
        return False

    if record.status == "rejected":
        print(
            f"[nre_agent] ts={_utc_now()} approval_key={key} "
            f"approval_gate=suppress approval_status=rejected",
            flush=True,
        )
        return False

    if record.status == "approved":
        # Consume the approval — clear and allow execution
        clear_approval_record(key)
        print(
            f"[nre_agent] ts={_utc_now()} approval_key={key} "
            f"approval_gate=proceed",
            flush=True,
        )
        return True

    return True


# ── BGP snapshot loading ──────────────────────────────────────────────────────

def _load_bgp_snapshot() -> dict[str, Any]:
    """
    Load the BGP snapshot JSON from NRE_AGENT_BGP_SNAPSHOT_FILE.

    In Kubernetes the snapshot is mounted from a ConfigMap at
    /data/bgp_snapshot.json. In future this will be replaced by a
    live gNMI poll via Capsule.
    """
    path = Path(
        os.environ.get(
            "NRE_AGENT_BGP_SNAPSHOT_FILE", "/tmp/bgp_snapshot.json"
        )
    )

    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("BGP snapshot file must contain a JSON object")

    return data


# ── BGP diagnostics iteration ─────────────────────────────────────────────────

def _run_bgp_diagnostics_iteration() -> None:
    """
    Execute one complete BGP diagnostics cycle.

    Steps:
      1.  Load BGP snapshot from disk
      2.  Call bgp.analyze via mcp_server → structured diagnosis
      3.  Build BgpDecision from the response
      4.  Fetch BGP RAG context from Qdrant (vendor knowledge enrichment)
      5.  Extract peer context for history and remediation follow-ups
      6a. Call bgp.history_query for removed routes on the flagged peer
      6b. Call bgp.remediation_plan for a read-only action plan
      7.  Build execution plan from the decision
      8.  Assemble enriched incident payload
      9a. Publish incident_snapshot event to Kafka
      9b. Publish plan_snapshot event to Kafka
      10. Persist plan to /data/plans for operator review
      11. Track plan changes and manage the approval gate
    """
    fabric   = os.environ.get("NRE_AGENT_BGP_FABRIC",  "default").strip() or "default"
    device   = os.environ.get("NRE_AGENT_BGP_DEVICE",  "unknown").strip() or "unknown"
    base_url = os.environ.get("NRE_AGENT_LATTICE_URL", "http://lattice:8080").strip()

    # ── Step 1: Load BGP snapshot ─────────────────────────────────────────────
    snapshot = _load_bgp_snapshot()

    # ── Step 2: BGP analysis via mcp_server → lattice ─────────────────────────
    response = call_lattice_bgp_diagnostics(
        fabric=fabric,
        device=device,
        snapshot=snapshot,
        base_url=base_url,
    )

    print("[nre_agent] lattice BGP diagnostics response:", flush=True)
    print(response, flush=True)

    # ── Step 3: Build structured BgpDecision ──────────────────────────────────
    decision = build_bgp_decision(response)

    # ── Step 4: BGP RAG context — vendor knowledge enrichment ─────────────────
    # Query Qdrant (via mcp_server bgp.rag_context) for documentation
    # chunks relevant to the vendor and anomaly type. These are attached
    # to the incident payload so operators can see which docs informed
    # the diagnosis. Returns empty list gracefully when not yet populated.
    vendor       = os.environ.get("NRE_AGENT_BGP_VENDOR", "").strip() or None
    anomaly_type = _extract_primary_anomaly_type(decision)

    rag_chunks = call_mcp_bgp_rag_context(
        vendor=vendor,
        anomaly_type=anomaly_type,
        device=device,
        limit=4,
    )

    if rag_chunks:
        print(
            f"[nre_agent] ts={_utc_now_iso()} bgp_rag_context "
            f"chunk_count={len(rag_chunks)} anomaly_type={anomaly_type}",
            flush=True,
        )
    else:
        print(
            f"[nre_agent] ts={_utc_now_iso()} bgp_rag_context=empty "
            f"(collection not yet populated — proceeding without RAG)",
            flush=True,
        )

    # ── Step 5: Extract peer context for history + remediation calls ──────────
    # Walk the proposed_actions list to find the first peer and afi_safi.
    # These are used to scope the history query and remediation plan.
    peer_for_followup:     str | None = None
    afi_safi_for_followup: str        = "ipv4_unicast"

    proposed_actions = response.get("proposed_actions", [])
    if isinstance(proposed_actions, list):
        for item in proposed_actions:
            if not isinstance(item, dict):
                continue
            target = item.get("target", {})
            if not isinstance(target, dict):
                continue
            peer_value = target.get("peer")
            if peer_value:
                peer_for_followup = str(peer_value)
            afi_value = target.get("afi_safi")
            if afi_value:
                afi_safi_for_followup = str(afi_value)
            if peer_for_followup:
                break

    # ── Step 6a: History query — which routes were removed? ───────────────────
    history_result: dict[str, Any] | None = None

    if peer_for_followup:
        try:
            history_result = call_mcp_bgp_history_query(
                query_type="removed_routes_between",
                device=device,
                peer=peer_for_followup,
                afi_safi=afi_safi_for_followup,
                direction="received",
                start_ts=1711812000000,
                end_ts=1711812600000,
                incident_id=decision.incident_id,
            )
            print("[nre_agent] MCP BGP history query response:", flush=True)
            print(history_result, flush=True)
        except Exception as exc:
            print(
                f"[nre_agent] MCP BGP history query failed: {exc}",
                flush=True,
            )

    # ── Step 6b: Remediation plan — what should we do? ────────────────────────
    remediation_plan_result: dict[str, Any] | None = None

    if peer_for_followup:
        try:
            remediation_plan_result = call_mcp_bgp_remediation_plan(
                device=device,
                peer=peer_for_followup,
                network_instance="default",
                afi_safi=afi_safi_for_followup,
                incident_id=decision.incident_id,
            )
            print("[nre_agent] MCP BGP remediation plan response:", flush=True)
            print(remediation_plan_result, flush=True)
        except Exception as exc:
            print(
                f"[nre_agent] MCP BGP remediation plan failed: {exc}",
                flush=True,
            )

    # ── Step 7: Build execution plan ──────────────────────────────────────────
    plan = build_execution_plan(decision)

    # ── Step 8: Assemble enriched incident payload ────────────────────────────
    # Carries diagnosis + history + remediation plan + RAG context.
    # Everything here is observability — it does not drive the approval gate.
    incident_payload = decision_to_dict(decision)

    if history_result is not None:
        incident_payload["history_analysis"] = history_result

    if remediation_plan_result is not None:
        incident_payload["remediation_analysis"] = remediation_plan_result

    # Attach RAG chunks so operators see which docs informed the diagnosis
    incident_payload["rag_context"] = {
        "chunk_count": len(rag_chunks),
        "chunks":      rag_chunks,
    }

    print(summarize_bgp_decision(decision), flush=True)
    print(incident_payload, flush=True)

    # ── Step 9a: Publish incident event to Kafka ──────────────────────────────
    publish_kafka_event(
        topic=os.environ.get(
            "NRE_AGENT_KAFKA_INCIDENT_TOPIC", "nre.incidents"
        ),
        key=decision.incident_id,
        payload={
            "event_type":    "incident_snapshot",
            "event_version": "v1",
            "ts":            _utc_now_iso(),
            "incident_id":   decision.incident_id,
            "fabric":        getattr(decision, "fabric", None),
            "device":        getattr(decision, "device", None),
            "root_cause":    getattr(decision, "root_cause", None),
            "payload":       incident_payload,
        },
    )

    # ── Step 9b: Publish plan event to Kafka ──────────────────────────────────
    plan_payload = execution_plan_to_dict(plan)

    print(summarize_execution_plan(plan), flush=True)
    print(plan_payload, flush=True)

    publish_kafka_event(
        topic=os.environ.get(
            "NRE_AGENT_KAFKA_PLAN_TOPIC", "nre.plans"
        ),
        key=plan.incident_id,
        payload={
            "event_type":    "plan_snapshot",
            "event_version": "v1",
            "ts":            _utc_now_iso(),
            "incident_id":   plan.incident_id,
            "plan_id":       plan.plan_id,
            "fabric":        plan.metadata.get("fabric"),
            "device":        plan.metadata.get("device"),
            "root_cause":    plan.metadata.get("root_cause"),
            "payload":       plan_payload,
        },
    )

    # ── Step 10: Persist plan to disk ─────────────────────────────────────────
    _write_plan_artifact(plan)

    # ── Step 11: Track plan changes and manage approval gate ──────────────────
    incident_key     = decision.incident_id
    plan_fingerprint = compute_plan_fingerprint(plan)
    change_class     = classify_plan_change(
        incident_id=incident_key,
        current_fingerprint=plan_fingerprint,
    )

    print(
        f"[nre_agent] ts={_utc_now()} incident_id={incident_key} "
        f"plan_change={change_class}",
        flush=True,
    )

    _apply_simulated_approval_override(incident_key)

    approval_record = get_approval_record(incident_key)

    if decision.approval_required and approval_record is None:
        reasons = [action.summary for action in decision.gated_actions]

        approval_record = create_pending_approval(
            scenario=incident_key,
            risk_level=_highest_gated_risk(decision),
            blast_radius_score=len(decision.gated_actions),
            reasons=reasons,
        )

        print(
            f"[nre_agent] ts={_utc_now()} incident_id={incident_key} "
            f"decision_action=approval_pending "
            f"approval_status={approval_record.status}",
            flush=True,
        )

        summary = summarize_approval_state(incident_key)
        if summary is not None:
            print(
                f"[nre_agent] ts={_utc_now()} incident_id={incident_key} "
                f"approval_record={summary}",
                flush=True,
            )

    plan_state = build_plan_state(
        plan=plan,
        approval_record=approval_record,
    )

    print(summarize_plan_state(plan_state), flush=True)
    print(plan_state_to_dict(plan_state), flush=True)

    write_plan_memory_record(
        incident_id=incident_key,
        fingerprint=plan_fingerprint,
        safe_step_count=len(plan.safe_steps),
        gated_step_count=len(plan.gated_steps),
        skipped_action_count=len(plan.skipped_actions),
        updated_at=_utc_now(),
    )

    if not decision.approval_required:
        print(
            f"[nre_agent] ts={_utc_now()} incident_id={incident_key} "
            f"decision_action=no_approval_required",
            flush=True,
        )


# ── Scenario mode helpers ─────────────────────────────────────────────────────

def _extract_risk(response: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the nested risk block out of a lattice response, if present."""
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    risk = result.get("risk")
    if not isinstance(risk, dict):
        return None
    return risk


def _summarize_response(scenario: str, response: dict[str, Any]) -> str:
    """Build a one-line summary for scenario-mode loop output."""
    status  = str(response.get("status",  "unknown"))
    message = str(response.get("message", ""))

    risk = _extract_risk(response)
    if risk is None:
        return (
            f"[nre_agent] ts={_utc_now()} "
            f"scenario={scenario} status={status} message=\"{message}\""
        )

    return (
        f"[nre_agent] ts={_utc_now()} "
        f"scenario={scenario} status={status} "
        f"risk_level={risk.get('risk_level', 'unknown')} "
        f"blast_radius={risk.get('blast_radius_score')} "
        f"requires_approval={risk.get('requires_approval')} "
        f"message=\"{message}\""
    )


def _handle_policy_outcome(scenario: str, response: dict[str, Any]) -> None:
    """Evaluate the risk block and escalate or continue."""
    risk = _extract_risk(response)
    if risk is None:
        print(
            f"[nre_agent] ts={_utc_now()} scenario={scenario} "
            f"policy_state=no_risk_data",
            flush=True,
        )
        return

    risk_level         = str(risk.get("risk_level", "unknown"))
    requires_approval  = bool(risk.get("requires_approval", False))
    blast_radius_score = int(risk.get("blast_radius_score", 0))
    reasons            = [str(x) for x in risk.get("reasons", [])]

    if requires_approval or risk_level == "high":
        if _is_in_cooldown(scenario):
            remaining = _get_cooldown_remaining_seconds(scenario)
            print(
                f"[nre_agent] ts={_utc_now()} scenario={scenario} "
                f"policy_action=cooldown remaining_seconds={remaining}",
                flush=True,
            )
            return

        record = create_pending_approval(
            scenario=scenario,
            risk_level=risk_level,
            blast_radius_score=blast_radius_score,
            reasons=reasons,
        )
        print(
            f"[nre_agent] ts={_utc_now()} scenario={scenario} "
            f"policy_action=escalate approval_status={record.status} "
            f"reasons={reasons}",
            flush=True,
        )
        return

    if risk_level == "medium":
        print(
            f"[nre_agent] ts={_utc_now()} scenario={scenario} "
            f"policy_action=caution reasons={reasons}",
            flush=True,
        )
        return

    print(
        f"[nre_agent] ts={_utc_now()} scenario={scenario} "
        f"policy_action=continue",
        flush=True,
    )


def _post_execution_bookkeeping(
    scenario: str, response: dict[str, Any]
) -> None:
    """Start cooldown for high-risk scenarios after execution."""
    risk = _extract_risk(response)
    if risk is None:
        return

    risk_level        = str(risk.get("risk_level", "unknown"))
    requires_approval = bool(risk.get("requires_approval", False))

    record = get_approval_record(scenario)
    if record is None and (requires_approval or risk_level == "high"):
        _set_cooldown(scenario)
        remaining = _get_cooldown_remaining_seconds(scenario)
        print(
            f"[nre_agent] ts={_utc_now()} scenario={scenario} "
            f"post_execution=cooldown_started remaining_seconds={remaining}",
            flush=True,
        )


# ── Plan persistence ──────────────────────────────────────────────────────────

def _write_plan_artifact(plan: Any) -> None:
    """
    Write the full execution plan to /data/plans/<plan_id>.json.

    The directory is a PVC in Kubernetes. Plans accumulate here for
    operator review and post-incident forensics.
    """
    plan_dir = Path(
        os.environ.get("NRE_AGENT_PLAN_MEMORY_DIR", "/data/plans")
    )
    plan_dir.mkdir(parents=True, exist_ok=True)

    plan_payload = execution_plan_to_dict(plan)
    plan_id      = str(plan_payload.get("plan_id", "unknown")).replace(":", "_")
    plan_path    = plan_dir / f"{plan_id}.json"

    plan_path.write_text(json.dumps(plan_payload, indent=2))


# ── Decision helpers ──────────────────────────────────────────────────────────

def _extract_primary_anomaly_type(decision: Any) -> str | None:
    """
    Return the action_type of the highest-priority gated action.

    Used to focus the BGP RAG query on the most relevant documentation
    section. Falls back to the first safe action, then None.
    """
    if decision.gated_actions:
        return getattr(decision.gated_actions[0], "action_type", None)
    if decision.safe_actions:
        return getattr(decision.safe_actions[0], "action_type", None)
    return None


def _highest_gated_risk(decision: Any) -> str:
    """Return the highest risk_level across all gated actions."""
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    best      = "low"
    best_rank = 0

    for action in decision.gated_actions:
        risk_level = str(action.risk_level)
        risk_rank  = rank.get(risk_level, 0)
        if risk_rank > best_rank:
            best      = risk_level
            best_rank = risk_rank

    return best


# ── Outer control loop ────────────────────────────────────────────────────────

def run_agent_loop() -> None:
    """
    Main agent loop. Runs forever with a sleep between iterations.

    Mode is read on every iteration so it can be changed via a ConfigMap
    update and pod restart without redeploying the image.
    """
    interval = _interval_seconds()
    mode     = _agent_mode()

    print(
        f"[nre_agent] starting loop interval={interval}s mode={mode}",
        flush=True,
    )

    while True:
        try:
            mode = _agent_mode()
            if mode == "bgp_diagnostics":
                _run_bgp_diagnostics_iteration()
                time.sleep(interval)
                continue

            if mode == "evpn_diagnostics":
                _run_evpn_diagnostics_iteration()
                time.sleep(interval)
                continue

            # ── Scenario mode ─────────────────────────────────────────────────
            scenario = get_next_scenario()
            print(f"[nre_agent] selected scenario: {scenario}", flush=True)

            _apply_simulated_approval_override(scenario)

            if not _precheck_approval_gate(scenario):
                time.sleep(interval)
                continue

            base_url = os.environ.get(
                "NRE_AGENT_LATTICE_URL", "http://lattice:8080"
            ).strip()
            response = call_lattice(scenario=scenario, base_url=base_url)

            print("[nre_agent] lattice response:", flush=True)
            print(response, flush=True)
            print(_summarize_response(scenario, response), flush=True)

            _handle_policy_outcome(scenario, response)
            _post_execution_bookkeeping(scenario, response)

        except Exception as exc:
            print(
                f"[nre_agent] ts={_utc_now()} "
                f"loop_error={type(exc).__name__} message={exc}",
                flush=True,
            )

        time.sleep(interval)

# ── EVPN diagnostics iteration ────────────────────────────────────────────────

# Two synthetic EVPN incidents that cycle every iteration.
# In production these would come from real device state via Capsule.
_EVPN_SCENARIOS = [
    {
        "incident_id":  "evpn:prod-dc-west:leaf-01:vtep:10.1.1.1:unreachable",
        "scenario":     "vtep_reachability_analysis",
        "capability":   "bgp_evpn_peer_state",
        "question":     (
            "VTEP 10.1.1.1 is unreachable from leaf-01. "
            "BGP EVPN session is established but the type-3 IMET route "
            "is missing from the EVPN table. BUM traffic flooding is broken."
        ),
        "vendor":       "arista",
        "nos_family":   "eos",
        "device":       "leaf-01",
        "fabric":       "prod-dc-west",
        "vtep":         "10.1.1.1",
        "vni":          10100,
    },
    {
        "incident_id":  "evpn:prod-dc-west:leaf-02:mac:00:50:56:aa:bb:cc:mobility",
        "scenario":     "mac_mobility_analysis",
        "capability":   "evpn_mac_vrf_state",
        "question":     (
            "MAC address 00:50:56:aa:bb:cc is flapping between leaf-01 "
            "and leaf-02 in VNI 10200. MAC mobility counter is incrementing "
            "rapidly. Possible duplicate MAC or misconfigured bond."
        ),
        "vendor":       "arista",
        "nos_family":   "eos",
        "device":       "leaf-02",
        "fabric":       "prod-dc-west",
        "mac":          "00:50:56:aa:bb:cc",
        "vni":          10200,
    },
]

_evpn_scenario_index = 0


def _run_evpn_diagnostics_iteration() -> None:
    """
    Execute one EVPN diagnostics cycle.

    Cycles through the two synthetic EVPN incidents on each iteration:
      1. VTEP unreachable — missing type-3 IMET route
      2. MAC mobility storm — rapid MAC flapping between VTEPs

    Steps:
      1. Select next EVPN scenario
      2. Call evpn.analyze via mcp_server → lattice EVPN analysis service
      3. Assemble incident payload with reasoning + governed plan
      4. Publish nre_evpn_incidents event to Kafka
      5. Publish nre_evpn_plans event to Kafka
    """
    global _evpn_scenario_index

    scenario_def = _EVPN_SCENARIOS[_evpn_scenario_index % len(_EVPN_SCENARIOS)]
    _evpn_scenario_index += 1

    incident_id = scenario_def["incident_id"]
    ts          = _utc_now_iso()

    print(
        f"[nre_agent] evpn_iteration scenario={scenario_def['scenario']} "
        f"device={scenario_def['device']}",
        flush=True,
    )

    # ── Step 2: Call evpn.analyze via mcp_server ──────────────────────────────
    try:
        from agent.client import call_mcp_evpn_analyze
        evpn_result = call_mcp_evpn_analyze(
            question=scenario_def["question"],
            vendor=scenario_def["vendor"],
            nos_family=scenario_def["nos_family"],
            scenario=scenario_def["scenario"],
            capability=scenario_def["capability"],
            device=scenario_def["device"],
            fabric=scenario_def["fabric"],
            vni=scenario_def.get("vni"),
            mac=scenario_def.get("mac"),
            incident_id=incident_id,
            timestamp_utc=ts,
        )
    except Exception as exc:
        print(
            f"[nre_agent] evpn_analyze_error={type(exc).__name__} message={exc}",
            flush=True,
        )
        return

    reasoning      = evpn_result.get("reasoning", {})
    governed_plan  = evpn_result.get("governed_plan", {})
    mcp_plan       = evpn_result.get("mcp_plan", {})

    findings       = reasoning.get("findings", [])
    likely_causes  = reasoning.get("likely_causes", [])
    safe_actions   = len(governed_plan.get("allowed_tools", []))
    gated_actions  = len(governed_plan.get("downgraded_tools", [])) + \
                     len(governed_plan.get("blocked_tools", []))
    approval_req   = governed_plan.get("requires_approval", False)
    risk_class     = mcp_plan.get("risk_class", "unknown")
    confidence     = mcp_plan.get("confidence", "unknown")

    print(
        f"[nre_agent] evpn_incident incident_id={incident_id} "
        f"scenario={scenario_def['scenario']} "
        f"risk={risk_class} confidence={confidence} "
        f"safe_actions={safe_actions} gated_actions={gated_actions} "
        f"approval_required={approval_req}",
        flush=True,
    )

    # ── Step 4: Publish incident event to Kafka ───────────────────────────────
    incident_payload = {
        "event_type":    "evpn_incident_snapshot",
        "event_version": "v1",
        "ts":            ts,
        "incident_id":   incident_id,
        "fabric":        scenario_def["fabric"],
        "device":        scenario_def["device"],
        "scenario":      scenario_def["scenario"],
        "vendor":        scenario_def["vendor"],
        "risk_class":    risk_class,
        "confidence":    confidence,
        "approval_required": approval_req,
        "safe_action_count":   safe_actions,
        "gated_action_count":  gated_actions,
        "findings":      findings,
        "likely_causes": likely_causes,
        "payload":       evpn_result,
    }

    publish_kafka_event(
        topic="nre.evpn_incidents",
        key=incident_id,
        payload=incident_payload,
    )

    # ── Step 5: Publish plan event to Kafka ───────────────────────────────────
    plan_payload = {
        "event_type":    "evpn_plan_snapshot",
        "event_version": "v1",
        "ts":            ts,
        "incident_id":   incident_id,
        "plan_id":       f"evpn_plan:{incident_id}",
        "fabric":        scenario_def["fabric"],
        "device":        scenario_def["device"],
        "scenario":      scenario_def["scenario"],
        "risk_class":    risk_class,
        "approval_required": approval_req,
        "safe_step_count":   safe_actions,
        "gated_step_count":  gated_actions,
        "payload":       evpn_result,
    }

    publish_kafka_event(
        topic="nre.evpn_plans",
        key=incident_id,
        payload=plan_payload,
    )

    print(
        f"[nre_agent] ts={ts} evpn_incident_id={incident_id} "
        f"published to kafka",
        flush=True,
    )
