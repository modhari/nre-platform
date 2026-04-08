"""
bgp_snapshot_writer.py — Capsule BGP snapshot writer entrypoint.

This is the main process that runs inside the capsule pod. It:
  1. Waits for the gnmi-simulator (or real gnmic) to produce
     /data/gnmic_bgp.json
  2. Calls the Capsule snapshot writer to translate it into
     /data/bgp_snapshot.json on every poll interval
  3. Logs a summary of what it wrote each time

The translation logic lives in:
  gnmi_collection_agent/bgp/snapshot_writer.py

This file is intentionally thin — it is just the entrypoint that
wires environment variables to the library and handles the startup
wait loop.

Environment variables:
  GNMIC_OUTPUT_FILE          path gnmic writes to
                             default: /data/gnmic_bgp.json
  SNAPSHOT_OUTPUT_FILE       path nre-agent reads from
                             default: /data/bgp_snapshot.json
  POLL_INTERVAL_SECONDS      how often to check for new gnmic output
                             default: 30
  FABRIC_NAME                fabric label written into every event
                             default: prod-dc-west
  STARTUP_WAIT_SECONDS       how long to wait for gnmic output on cold
                             start before giving up and exiting
                             default: 300
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

LOG = logging.getLogger(__name__)


def _gnmic_output_file() -> Path:
    return Path(os.getenv("GNMIC_OUTPUT_FILE", "/data/gnmic_bgp.json"))


def _startup_wait() -> int:
    return int(os.getenv("STARTUP_WAIT_SECONDS", "300"))


def _wait_for_gnmic_output(path: Path, timeout_s: int) -> bool:
    """
    Block until the gnmic output file exists and has content.

    Returns True if the file appeared within timeout_s seconds.
    Returns False if the timeout was reached — the caller should exit.

    On a cold start the gnmi-simulator pod may take a few seconds to
    write its first output. We wait here rather than crashing immediately
    so the two pods can start in any order.
    """
    deadline = time.time() + timeout_s
    logged   = False

    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            LOG.info("gnmic output found at %s — starting translation loop", path)
            return True

        if not logged:
            LOG.info(
                "waiting for gnmic output at %s "
                "(timeout=%ds) ...",
                path, timeout_s,
            )
            logged = True

        time.sleep(5)

    LOG.error(
        "gnmic output not found at %s after %ds — exiting. "
        "Is the gnmi-simulator or gnmic pod running?",
        path, timeout_s,
    )
    return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    LOG.info("capsule bgp-snapshot-writer starting")

    # ── Wait for gnmic output before starting the translation loop ────────────
    gnmic_file = _gnmic_output_file()
    if not _wait_for_gnmic_output(gnmic_file, _startup_wait()):
        raise SystemExit(1)

    # ── Run the translation loop ──────────────────────────────────────────────
    # Import here so startup errors in the library surface clearly
    from gnmi_collection_agent.bgp.snapshot_writer import run
    run()


if __name__ == "__main__":
    main()
