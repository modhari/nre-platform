FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY internal ./internal

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data/generated/schema
COPY data/generated/schema/evpn_vxlan_coverage_summary.json ./data/generated/schema/

RUN useradd -m appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "datacenter_orchestrator.service:app", "--host", "0.0.0.0", "--port", "8080"]
