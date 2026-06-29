# Observability Dev

A local Podman-based observability playground with separate stacks for:

- monitoring: Prometheus, Loki, Grafana
- tracing: Tempo, OpenTelemetry Collector
- search and analytics: OpenSearch, OpenSearch Dashboards, and Data Prepper
- sample workload: `order-sample-service`

The repository is intentionally split by compose file so each stack can be started independently.

## Layout

- `compose/monitoring/compose.yaml`: main monitoring stack
- `compose/trace/compose.yaml`: tracing stack
- `compose/opensearch/compose.yaml`: OpenSearch + Data Prepper + OpenSearch Dashboards
- `compose/podman-rootful/compose.yaml`: extra rootful Podman-specific services
- `data-prepper/config/data-prepper-config.yaml`: Data Prepper server configuration
- `data-prepper/pipelines/pipelines.yaml`: Data Prepper trace analytics pipelines
- `opensearch/config/opensearch.yml`: OpenSearch node configuration
- `opensearch/config/opensearch_dashboards.yml`: OpenSearch Dashboards configuration
- `otel-collector/config.yml`: OpenTelemetry Collector fan-out to Tempo and Data Prepper
- `.env`: local secrets and variables, including `OPENSEARCH_ADMIN_PASSWORD`

## Quick Start

Run all commands from the repository root, not from a compose subdirectory.

1. Make sure the `observability` network already exists.
2. Fill in `.env` with your local values.
3. Start the stack you need:

```bash
podman-compose -f compose/monitoring/compose.yaml up -d
podman-compose -f compose/trace/compose.yaml up -d
podman-compose -f compose/opensearch/compose.yaml up -d
```

For trace analytics in OpenSearch, run both the tracing stack and the OpenSearch stack so the collector can forward traces to Data Prepper.

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
- [docs/opensearch.md](docs/opensearch.md)
