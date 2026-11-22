# Observability Dev

A local Podman-based observability playground with stacks for:

- observability: Prometheus, Loki, Grafana, Tempo, and OpenTelemetry Collector
- search and analytics: OpenSearch, OpenSearch Dashboards, and Data Prepper
- sample workload: `order-sample-service`

The repository is intentionally split by compose file so each stack can be started independently.

## Layout

- `compose/observability/compose.yaml`: metrics, logs, traces, and visualization stack
- `compose/opensearch/compose.yaml`: OpenSearch + Data Prepper + OpenSearch Dashboards
- `compose/podman-rootful/compose.yaml`: extra rootful Podman-specific services
- `kubernetes/otel-collector-service.yaml`: internal Kubernetes Service for OTLP ingestion
- `data-prepper/config/data-prepper-config.yaml`: Data Prepper server configuration
- `data-prepper/pipelines/pipelines.yaml`: Data Prepper trace analytics pipelines
- `opensearch/config/opensearch.yml`: OpenSearch node configuration
- `opensearch/config/opensearch_dashboards.yml`: OpenSearch Dashboards configuration
- `otel-collector/config.yml`: OpenTelemetry Collector pipelines for traces, metrics, and logs
- `obi/config.yml`: standalone OBI Config v2 that exports eBPF traces and metrics to the existing Collector
- `.env`: local secrets and variables, including `OPENSEARCH_ADMIN_PASSWORD`

## Quick Start

Run all commands from the repository root, not from a compose subdirectory.

### Podman container metrics

The Podman exporter uses a dedicated user-systemd API socket so Podman Desktop
cannot replace the socket inode used by the exporter. Install and enable the
units before creating the exporter container:

```bash
mkdir -p ~/.config/systemd/user
install -m 0644 systemd/podman-exporter-api.service \
  systemd/podman-exporter-api.socket ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now podman-exporter-api.socket
```

The socket unit creates `/run/user/1000/podman-exporter-api/`, which is mounted
into `podman-exporter`. The API service starts automatically on the first scrape
and remains independent of Podman Desktop.

1. Make sure the `observability` network already exists.
2. Copy `.env.example` to `.env`, then replace the example passwords with your local values.
3. Start the stack you need:

```bash
cp .env.example .env
podman-compose -f compose/observability/compose.yaml up -d
podman-compose -f compose/opensearch/compose.yaml up -d
```

For trace analytics in OpenSearch, run both the tracing stack and the OpenSearch stack so the collector can forward traces to Data Prepper.

## Kubernetes Service DNS

The Kubernetes manifest creates a `ClusterIP` Service named `otel-collector` in the `observability` namespace. Apply it with:

```bash
kubectl apply -f kubernetes/otel-collector-service.yaml
```

The collector workload must use the label `app.kubernetes.io/name: otel-collector` so the Service can route traffic to its Pods. Workloads in the cluster can then use:

- OTLP gRPC: `otel-collector.observability.svc.cluster.local:4317`
- OTLP HTTP: `http://otel-collector.observability.svc.cluster.local:4318`

The shorter in-cluster names `otel-collector.observability.svc` and `otel-collector` also resolve from the appropriate namespace. This repository does not include a Kubernetes Deployment for the collector, so the Service is intentionally separate from the existing local Podman Compose stack.

OTLP logs received by the collector are forwarded to Loki through its native OTLP HTTP endpoint. Grafana queries the stored logs from the provisioned Loki data source.

## OpenSearch At A Glance

- OpenSearch is the storage, indexing, and query engine.
- OpenSearch Dashboards is the UI for exploration, dashboards, visualizations, and workspaces.
- Data Prepper is installed in the OpenSearch stack and receives trace data from the OpenTelemetry Collector before writing trace analytics documents to OpenSearch.

Current local OpenSearch stack:

- OpenSearch version: `3.7.0`
- OpenSearch Dashboards version: `3.7.0`
- Data Prepper version: `2.15.1`
- OpenSearch endpoint: `https://localhost:9200`
- Dashboards endpoint: `http://localhost:5601`
- Data Prepper API endpoint: `http://localhost:4900/list`
- Data Prepper trace ingest: `data-prepper:21890` on the `observability` network
- login user: `admin`
- login password: read from `OPENSEARCH_ADMIN_PASSWORD` in `.env`
- prepared workspaces: `Observability` and `Security`
- trace analytics indices: `otel-v1-apm-span-*` and `otel-v1-apm-service-map`

About `kibanaserver`:

- `kibanaserver` in the Dashboards config is the internal service account Dashboards uses to talk to OpenSearch
- it is not the main human login account for the UI

## UI Vs Config

Use the UI for:

- creating workspaces
- creating dashboards and visualizations
- managing data views or index patterns
- changing workspace content and saved objects

Use config files for:

- image and container version
- ports, volumes, networks, and environment variables
- enabling or disabling Dashboards features
- the Dashboards-to-OpenSearch connection
- startup-level defaults such as default route and workspace mode

## Docs

- [docs/README.md](docs/README.md)
- [docs/ebpf.md](docs/ebpf.md)
- [docs/opensearch.md](docs/opensearch.md)
