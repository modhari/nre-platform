from __future__ import annotations

import os
import threading

import uvicorn

from pathlib import Path
import json

from agent.approvals_api import app
from agent.loop import run_agent_loop

def save_plan(plan: dict):
    base = Path("/data/plans")
    base.mkdir(parents=True, exist_ok=True)

    plan_id = plan.get("plan_id", "unknown").replace(":", "_")
    path = base / f"{plan_id}.json"

    path.write_text(json.dumps(plan, indent=2))

def _run_api_server() -> None:
    """
    Run the approvals API server.

    The port is configurable so local development can avoid collisions.
    """
    host = os.environ.get("NRE_AGENT_API_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.environ.get("NRE_AGENT_API_PORT", "8090"))

    uvicorn.run(app, host=host, port=port)


def _api_enabled() -> bool:
    """
    Decide whether the approvals API should start.

    Default is disabled for local development because most local validation only
    needs the agent loop.
    """
    value = os.environ.get("NRE_AGENT_ENABLE_API", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def main() -> None:
    """
    Entrypoint for the local agent process.

    Behavior:
    - always runs the agent loop
    - starts the approvals API only when explicitly enabled
    """
    if _api_enabled():
        api_thread = threading.Thread(target=_run_api_server, daemon=True)
        api_thread.start()

    run_agent_loop()


if __name__ == "__main__":
    main()
