"""
run.py — Capsule supervisor.

Runs both snapshot writers as parallel processes:
  bgp_snapshot_writer   — /data/gnmic_bgp.json  → /data/bgp_snapshot.json
  evpn_snapshot_writer  — /data/gnmic_evpn.json  → /data/evpn_snapshot.json

If either writer crashes it is restarted after a 5s delay.
The supervisor exits only if both writers fail repeatedly.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

LOG = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

WRITERS = [
    {
        "name":   "bgp-snapshot-writer",
        "script": str(Path(__file__).parent / "bgp_snapshot_writer.py"),
    },
    {
        "name":   "evpn-snapshot-writer",
        "script": str(Path(__file__).parent / "evpn_snapshot_writer.py"),
    },
]

MAX_RESTARTS = 10
RESTART_DELAY = 5


def run() -> None:
    procs: dict[str, subprocess.Popen] = {}
    restart_counts: dict[str, int] = {w["name"]: 0 for w in WRITERS}

    # ── Start all writers ──────────────────────────────────────────────────
    for writer in WRITERS:
        name   = writer["name"]
        script = writer["script"]
        LOG.info("starting %s", name)
        procs[name] = subprocess.Popen(
            [sys.executable, script],
            env=os.environ.copy(),
        )

    # ── Supervisor loop ────────────────────────────────────────────────────
    while True:
        time.sleep(5)

        for writer in WRITERS:
            name   = writer["name"]
            script = writer["script"]
            proc   = procs.get(name)

            if proc is None:
                continue

            ret = proc.poll()
            if ret is None:
                continue  # still running

            restart_counts[name] += 1
            if restart_counts[name] > MAX_RESTARTS:
                LOG.error(
                    "%s has crashed %d times — not restarting",
                    name, restart_counts[name],
                )
                continue

            LOG.warning(
                "%s exited with code %d — restarting (attempt %d/%d)",
                name, ret, restart_counts[name], MAX_RESTARTS,
            )
            time.sleep(RESTART_DELAY)
            procs[name] = subprocess.Popen(
                [sys.executable, script],
                env=os.environ.copy(),
            )

        # Exit if all writers have exceeded restart limit
        if all(restart_counts[w["name"]] > MAX_RESTARTS for w in WRITERS):
            LOG.error("all writers have exceeded restart limit — exiting")
            sys.exit(1)


if __name__ == "__main__":
    run()
