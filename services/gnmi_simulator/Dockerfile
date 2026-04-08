# =============================================================================
# gnmi-simulator — synthetic BGP telemetry generator
#
# Generates realistic OpenConfig BGP state for four vendors and writes
# gnmic event-format JSON to a shared PVC. The capsule bgp-snapshot-writer
# reads this file and translates it into bgp_snapshot.json for nre-agent.
#
# When real devices are available, remove this service from the Helm chart
# and deploy gnmic pointing at real devices writing to the same file path.
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

# No external dependencies — stdlib only
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulator.py .

# Run as non-root
RUN useradd -m -u 1000 capsule
USER capsule

ENV GNMIC_OUTPUT_FILE=/data/gnmic_bgp.json
ENV SCENARIO_DURATION_SECONDS=120
ENV POLL_INTERVAL_SECONDS=30
ENV FABRIC_NAME=prod-dc-west

CMD ["python", "simulator.py"]
