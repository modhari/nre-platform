# =============================================================================
# NRE Platform — Local Development Makefile
#
# QUICK START (cold machine, first time):
#   make up
#
# DAY-TO-DAY (already have a cluster):
#   make deploy                  # re-deploy helm after values changes
#   make dev SERVICE=nre-agent   # rebuild + redeploy ONE service after code changes
#   make logs SERVICE=nre-agent  # tail logs for a service
#   make status                  # show all pod health
#   make smoke                   # hit every service endpoint
#
# TEARDOWN:
#   make down                    # delete the kind cluster
# =============================================================================

CLUSTER_NAME  := nre-platform
NAMESPACE     := nre-platform
HELM_RELEASE  := nre-platform
HELM_CHART    := deploy/helm/nre-platform
VALUES_LOCAL  := $(HELM_CHART)/values.local.yaml
KIND_CONFIG   := kind-config.yaml

IMAGES := \
	nre-agent:local \
	mcp-server:local \
	lattice:local \
	lattice-mcp:local \
	ecmp-trace:local \
	kafka-influx-writer:local

.PHONY: up down build load deploy cluster-up cluster-down \
        build-% load-% dev status logs smoke help

.DEFAULT_GOAL := help

## up: Full cold start — create cluster, build all images, deploy everything.
up: cluster-up build load deploy
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  NRE Platform is up."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  mcp-server   →  http://localhost:8080/mcp"
	@echo "  nre-agent    →  http://localhost:8090"
	@echo "  lattice      →  http://localhost:8100"
	@echo "  lattice-mcp  →  http://localhost:8101"
	@echo "  ecmp-trace   →  http://localhost:8081"
	@echo "  qdrant       →  http://localhost:6333"
	@echo "  kafka        →  localhost:9092"
	@echo "  influxdb     →  http://localhost:8086"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Run 'make smoke' to verify all endpoints."
	@echo ""

## down: Delete the kind cluster.
down: cluster-down

## cluster-up: Create the kind cluster if it does not already exist.
cluster-up:
	@if kind get clusters 2>/dev/null | grep -q "^$(CLUSTER_NAME)$$"; then \
		echo "[cluster] '$(CLUSTER_NAME)' already exists — skipping create"; \
	else \
		echo "[cluster] creating '$(CLUSTER_NAME)'..."; \
		kind create cluster --name $(CLUSTER_NAME) --config $(KIND_CONFIG); \
	fi
	@kubectl config use-context kind-$(CLUSTER_NAME)

## cluster-down: Destroy the kind cluster.
cluster-down:
	kind delete cluster --name $(CLUSTER_NAME)

## build: Build all service images.
build: build-nre-agent build-mcp-server build-lattice build-lattice-mcp build-ecmp-trace build-kafka-influx-writer

build-nre-agent:
	@echo "[build] nre-agent..."
	docker build -t nre-agent:local services/nre_agent/

build-mcp-server:
	@echo "[build] mcp-server..."
	docker build -t mcp-server:local services/mcp_server/

build-lattice:
	@echo "[build] lattice..."
	docker build -t lattice:local -f services/lattice/Dockerfile services/lattice/

build-lattice-mcp:
	@echo "[build] lattice-mcp..."
	docker build -t lattice-mcp:local -f services/lattice/Dockerfile.mcp services/lattice/

build-ecmp-trace:
	@echo "[build] ecmp-trace..."
	docker build -t ecmp-trace:local services/ecmp_trace/

build-kafka-influx-writer:
	@echo "[build] kafka-influx-writer..."
	docker build -t kafka-influx-writer:local services/observability/

## load: Load all locally-built images into the kind cluster.
load:
	@for img in $(IMAGES); do \
		echo "[load] $$img → kind/$(CLUSTER_NAME)"; \
		kind load docker-image $$img --name $(CLUSTER_NAME); \
	done

load-%:
	kind load docker-image $*:local --name $(CLUSTER_NAME)

## deploy: Install or upgrade the Helm release.
deploy:
	@echo "[helm] upgrading release '$(HELM_RELEASE)'..."
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) \
		--namespace $(NAMESPACE) \
		--create-namespace \
		-f $(VALUES_LOCAL) \
		--wait \
		--timeout 8m
	@echo "[helm] release '$(HELM_RELEASE)' is live"

## dev: Rebuild, reload, and restart one service. Usage: make dev SERVICE=nre-agent
dev:
ifndef SERVICE
	$(error SERVICE is required.  Usage: make dev SERVICE=nre-agent)
endif
	@echo "[dev] rebuilding $(SERVICE)..."
	$(MAKE) build-$(SERVICE)
	$(MAKE) load-$(SERVICE)
	kubectl rollout restart deployment/$(SERVICE) -n $(NAMESPACE)
	kubectl rollout status  deployment/$(SERVICE) -n $(NAMESPACE) --timeout=3m

## status: Show pod health.
status:
	kubectl get pods -n $(NAMESPACE) -o wide

## logs: Tail logs. Usage: make logs SERVICE=nre-agent
logs:
ifndef SERVICE
	$(error SERVICE is required.  Usage: make logs SERVICE=nre-agent)
endif
	kubectl logs -n $(NAMESPACE) -l app=$(SERVICE) --tail=200 -f

## smoke: Hit every service endpoint.
smoke:
	@echo ""
	@echo "── smoke test ─────────────────────────────────────"
	@curl -sf http://localhost:8081/ -o /dev/null && echo "  ecmp-trace   OK" || echo "  ecmp-trace   FAIL"
	@curl -sf http://localhost:6333/ -o /dev/null && echo "  qdrant       OK" || echo "  qdrant       FAIL"
	@curl -sf http://localhost:8086/ping -o /dev/null && echo "  influxdb     OK" || echo "  influxdb     FAIL"
	@curl -sf http://localhost:8101/health/ready -o /dev/null && echo "  lattice-mcp  OK" || echo "  lattice-mcp  FAIL"
	@echo "───────────────────────────────────────────────────"
	@echo ""

## help: Print this help.
help:
	@grep -E '^##' $(MAKEFILE_LIST) | sed 's/## /  /'

## post-install: Run after 'make up' — sets up InfluxDB and patches nre-agent NodePort.
post-install:
	@echo "[post-install] waiting for influxdb to be ready..."
	@kubectl wait --for=condition=ready pod -l app=influxdb -n $(NAMESPACE) --timeout=120s
	@echo "[post-install] setting up InfluxDB org/bucket/token..."
	@kubectl exec -n $(NAMESPACE) deploy/influxdb -- influx setup \
		--username nreadmin \
		--password nreadminpassword \
		--org nre \
		--bucket nre \
		--token nreadminsupersecrettoken \
		--force 2>&1 | grep -v "^$$" || true
	@echo "[post-install] patching nre-agent NodePort to 30090..."
	@kubectl patch svc nre-agent -n $(NAMESPACE) \
		-p '{"spec":{"type":"NodePort","ports":[{"port":8090,"targetPort":8090,"nodePort":30090}]}}' \
		2>/dev/null || true
	@kubectl rollout restart deployment/kafka-influx-writer -n $(NAMESPACE)
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  post-install complete. Run 'make smoke' to verify."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

## push: Tag and push all locally built images to ghcr.io/modhari/
REGISTRY := ghcr.io/modhari

push: push-nre-agent push-mcp-server push-lattice push-lattice-mcp push-ecmp-trace push-kafka-influx-writer
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  All images pushed to $(REGISTRY)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

push-%:
	docker tag $*:local $(REGISTRY)/$*:latest
	docker push $(REGISTRY)/$*:latest
