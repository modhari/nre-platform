# NRE Platform

Autonomous network reliability engineering platform. Detects BGP incidents, correlates root causes, proposes remediation plans, and gates execution behind human approval — all running locally on kind with one command.

## Architecture
## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) >= 0.31
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [helm](https://helm.sh/docs/intro/install/) >= 4.0

## Quick Start

```bash
git clone https://github.com/modhari/nre-platform
cd nre-platform
make up
make post-install
make smoke
```

`make up` takes 5–10 minutes on first run (pulls base images, builds all services, deploys to kind).

## Endpoints

| Service | URL |
|---|---|
| mcp-server | http://localhost:8080/mcp |
| nre-agent approvals | http://localhost:8090/approvals |
| lattice | http://localhost:8100 |
| lattice-mcp | http://localhost:8101/health/ready |
| ecmp-trace | http://localhost:8081 |
| qdrant | http://localhost:6333 |
| kafka | localhost:9092 |
| influxdb | http://localhost:8086 |

## Usage

### Check what the agent detected

```bash
curl -s http://localhost:8090/approvals | python3 -m json.tool
```

### Approve a pending remediation

```bash
curl -s -X POST http://localhost:8090/approvals/<incident_id>/approve
```

### Watch the agent loop

```bash
make logs SERVICE=nre-agent
```

### Check all pod health

```bash
make status
```

## Day-to-day development

```bash
# Rebuild and redeploy one service after code changes
make dev SERVICE=nre-agent
make dev SERVICE=lattice-mcp

# Tear down and rebuild everything from scratch
make down
make up
make post-install
```

## What the demo does

On startup, `nre-agent` loads a BGP snapshot showing three peers on `leaf-01` with a shared dependency on route-reflector `rr-01`:

- `10.0.0.12` — session idle, tcp_connect_failed
- `10.0.0.13` — session idle, tcp_connect_failed  
- `10.0.0.11` — session established, zero prefixes received

The agent correlates these into one parent incident, generates 4 safe read-only validation steps and 1 gated remediation (BGP session reset), and holds execution pending operator approval. Approve it with:

```bash
curl -s -X POST \
  "http://localhost:8090/approvals/fabric:prod-dc-west:device:leaf-01:root:rr-01:window:180/approve"
```

## Services

| Service | Language | Role |
|---|---|---|
| nre-agent | Python | Autonomous diagnostic loop, approval gate, Kafka publisher |
| mcp-server | Python | MCP capability gateway, routes to all backend services |
| lattice | Python | BGP/EVPN analysis engine, YANG schema intelligence |
| lattice-mcp | Python | BGP history store (PVC-backed), remediation planner |
| ecmp-trace | Go | ECMP path tracing |
| kafka-influx-writer | Python | Kafka → InfluxDB observability pipeline |
| qdrant | - | Vector store for RAG knowledge (EVPN + BGP docs) |
| kafka | - | Event bus (nre.incidents, nre.plans topics) |
| influxdb | - | Metrics and event storage |
