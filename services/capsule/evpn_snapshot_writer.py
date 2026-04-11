"""
evpn_snapshot_writer.py — Capsule EVPN snapshot writer entrypoint.

Reads /data/gnmic_evpn.json (written by gnmi-simulator or real gnmic)
and translates it into /data/evpn_snapshot.json which nre-agent reads
on every EVPN diagnostic loop iteration.

Environment variables:
  GNMIC_EVPN_OUTPUT_FILE      default: /data/gnmic_evpn.json
  EVPN_SNAPSHOT_OUTPUT_FILE   default: /data/evpn_snapshot.json
  POLL_INTERVAL_SECONDS       default: 30
  FABRIC_NAME                 default: prod-dc-west
  MAC_MOBILITY_THRESHOLD      default: 5
  TYPE5_SPIKE_THRESHOLD       default: 50
  STARTUP_WAIT_SECONDS        default: 300
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

LOG = logging.getLogger(__name__)


def _gnmic_evpn_file() -> Path:
    return Path(os.getenv("GNMIC_EVPN_OUTPUT_FILE", "/data/gnmic_evpn.json"))


def _startup_wait() -> int:
    return int(os.getenv("STARTUP_WAIT_SECONDS", "300"))


def _wait_for_input(path: Path, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    logged   = False

    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            LOG.info("gnmic EVPN output found at %s — starting translation loop", path)
            return True

        if not logged:
            LOG.info(
                "waiting for gnmic EVPN output at %s (timeout=%ds) ...",
                path, timeout_s,
            )
            logged = True

        time.sleep(5)

    LOG.error(
        "gnmic EVPN output not found at %s after %ds — exiting.",
        path, timeout_s,
    )
    return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    LOG.info("capsule evpn-snapshot-writer starting")

    evpn_file = _gnmic_evpn_file()
    if not _wait_for_input(evpn_file, _startup_wait()):
        raise SystemExit(1)

    from gnmi_collection_agent.bgp.evpn_snapshot_writer import run
    run()


if __name__ == "__main__":
    main()
