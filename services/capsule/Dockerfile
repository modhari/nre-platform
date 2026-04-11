# =============================================================================
# capsule — BGP snapshot writer
#
# Reads gnmic event-format JSON from /data/gnmic_bgp.json (written by
# gnmi-simulator or real gnmic) and translates it into /data/bgp_snapshot.json
# which nre-agent reads on every diagnostic loop iteration.
#
# The Capsule library is installed from the services/capsule/src/ tree which
# is a copy of ~/git/Capsule/src/. The Makefile build step copies the source
# in before docker build runs.
#
# Directory layout inside the image:
#   /app/src/gnmi_collection_agent/   — Capsule library
#   /app/bgp_snapshot_writer.py       — entrypoint
#   /app/requirements.txt
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

# ── Install system deps ───────────────────────────────────────────────────────
# No C extensions needed — pure Python.
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# ── Install Python dependencies ───────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Install Capsule library from source ───────────────────────────────────────
# The Makefile copies ~/git/Capsule/src/ into services/capsule/src/
# before building the image so the snapshot_writer module is available.
COPY src/ ./src/
COPY setup.py setup.cfg ./
RUN pip install --no-cache-dir -e .

# ── Copy entrypoint ───────────────────────────────────────────────────────────
COPY bgp_snapshot_writer.py .
COPY evpn_snapshot_writer.py .

# ── Run as non-root ───────────────────────────────────────────────────────────
RUN useradd -m -u 1000 capsule
USER capsule

# ── Environment defaults ──────────────────────────────────────────────────────
ENV GNMIC_OUTPUT_FILE=/data/gnmic_bgp.json
ENV SNAPSHOT_OUTPUT_FILE=/data/bgp_snapshot.json
ENV GNMIC_EVPN_OUTPUT_FILE=/data/gnmic_evpn.json
ENV EVPN_SNAPSHOT_OUTPUT_FILE=/data/evpn_snapshot.json
ENV POLL_INTERVAL_SECONDS=30
ENV FABRIC_NAME=prod-dc-west
ENV STARTUP_WAIT_SECONDS=300
ENV MAC_MOBILITY_THRESHOLD=5
ENV TYPE5_SPIKE_THRESHOLD=50

COPY run.py .

CMD ["python", "run.py"]
