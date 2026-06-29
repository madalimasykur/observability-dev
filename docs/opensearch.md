# OpenSearch Notes

This document focuses on the OpenSearch stack in this repository.

## Current Local State

Files involved:

- `compose/opensearch/compose.yaml`
- `data-prepper/config/data-prepper-config.yaml`
- `data-prepper/pipelines/pipelines.yaml`
- `opensearch/config/opensearch.yml`
- `opensearch/config/opensearch_dashboards.yml`
- `otel-collector/config.yml`
- `.env`

Current local behavior:

- OpenSearch runs as a single node
- security mode is enabled
- Data Prepper runs in the same compose stack as OpenSearch and Dashboards
- Data Prepper receives OTLP trace traffic on port `21890`
- Data Prepper exposes a local API on `http://localhost:4900`
- the OpenTelemetry Collector exports traces to both Tempo and Data Prepper
- Data Prepper writes trace analytics documents into `otel-v1-apm-span-*` and `otel-v1-apm-service-map`
- OpenSearch Dashboards runs on the `observability` network
- UI login user: `admin`
- UI login password: `OPENSEARCH_ADMIN_PASSWORD` from `.env`
- available workspaces: `Observability` and `Security`

## What Is What

### OpenSearch

OpenSearch is the storage and query backend.

Its main responsibilities are:

- receiving documents or events
- storing and indexing data
- running search and aggregations
- acting as the data backend for dashboards and visualizations

### OpenSearch Dashboards

OpenSearch Dashboards is the UI layer on top of OpenSearch.

Its main responsibilities are:

- login and workspace management
- data exploration through Discover
- creating dashboards and visualizations
- exposing observability and security analytics features

### Data Prepper

Data Prepper is an ingest and transform component, not a search database.

It is typically used to:

- receive upstream data
- parse, enrich, filter, or route events
- forward the processed result to OpenSearch

A simple way to think about it:

- Data Prepper: the data pipeline
- OpenSearch: the storage, index, and query engine
- Dashboards: the UI used to consume the data

In this repository, Data Prepper is specifically used for trace analytics ingestion:

- `otel-collector` receives OTLP traces from sample workloads or smoke tests
- `otel-collector` forwards traces to Tempo and to Data Prepper
- Data Prepper converts those traces into OpenSearch trace analytics documents
- Dashboards can then use the `Observability` workspace against that indexed trace data

## Data Prepper Vs OpenSearch

| Component | Main role | Typical position |
| --- | --- | --- |
| Data Prepper | ingest, transform, enrich, route | before OpenSearch |
| OpenSearch | store, index, search, aggregate | main backend |
| Dashboards | UI and visualization | on top of OpenSearch |

This repository already uses Data Prepper because the trace analytics experience benefits from a dedicated ingest stage.

If you later want to:

- parse raw logs
- enrich traces or events
- fan out data into a dedicated ingest pipeline

then Data Prepper remains a good fit.

If you only need to:

- store data
- query data
- build dashboards

then OpenSearch + Dashboards is usually enough.

## Why `kibanaserver` Appears

In `opensearch/config/opensearch_dashboards.yml` the current config contains:

```yaml
opensearch.username: kibanaserver
opensearch.password: kibanaserver
```

That is expected.

It means:

- `kibanaserver` is the internal service account used for the Dashboards-to-OpenSearch connection
- it is not the main human login account
- humans still log in to the UI with accounts such as `admin`

Why is the name still `kibanaserver`?

- OpenSearch Dashboards has historical lineage from Kibana
- that compatibility-oriented naming is still used in parts of the source and security plugin
- in the image currently running here, Dashboards source still defaults `opensearch.username/password` to `kibanaserver`

So the short version is:

- `admin`: human login user
- `kibanaserver`: internal Dashboards service user for OpenSearch access

## Workspaces And Modes

A workspace is a scoped experience built from:

- the menus that are shown
- the features that are available
- the relevant saved objects
- the permissions assigned to users or groups

A workspace is not a separate product. It is more like a packaged use case and access boundary.

### Observability Workspace

The `Observability` workspace is suited for:

- logs
- metrics
- traces
- application overview
- operational dashboards and visualizations

In this local build, the observability mode brings features such as:

- `discover`
- `dashboards`
- `visualize`
- `observability-metrics`
- `observability-traces`
- `observability-applications`

So if your office environment has a workspace centered on trace, logs, and metrics overview, that is usually the `Observability` mode.

### Security Workspace

The `Security` workspace in this repository was created with the `security-analytics` use case.

It is suited for:

- security analytics
- detections
- investigative views
- dashboards and visualizations related to security

### What Dashboard, Visualize, And Discover Are

`Dashboard`, `Visualize`, and `Discover` are not separate modes.

They are tools available inside a workspace.

A better mental model is:

- mode or use case: `Observability`, `Security`, `Search`, `Essentials`
- tools inside the mode: `Discover`, `Dashboard`, `Visualize`, and others

## What Each File Controls

### `compose/opensearch/compose.yaml`

Controls container-level behavior:

- image and version
- published ports
- network
- bind-mounted volumes
- environment variables
- the initial OpenSearch admin password
- the Data Prepper service lifecycle

Important examples in the current setup:

- OpenSearch image `3.7.0`
- Dashboards image `3.7.0`
- Data Prepper image `2.15.1`
- `OPENSEARCH_INITIAL_ADMIN_PASSWORD=${OPENSEARCH_ADMIN_PASSWORD}`
- Data Prepper API port `4900`
- Data Prepper trace ingest port `21890`

### `data-prepper/config/data-prepper-config.yaml`

Controls the Data Prepper server itself:

- whether the local API uses TLS
- which port the API binds to

In this repository it is intentionally simple for local development:

- API TLS is disabled
- API port is `4900`

### `data-prepper/pipelines/pipelines.yaml`

Controls the trace analytics ingest flow:

- the OTLP trace source
- the raw trace pipeline
- the service map pipeline
- the OpenSearch sinks and index types

Important examples in the current setup:

- `otel_trace_source` listens on `21890`
- raw spans are written with `index_type: trace-analytics-raw`
- service map documents are written with `index_type: trace-analytics-service-map`
- `trace_flush_interval: 5` keeps local trace visibility fast
- `window_duration: 10` makes local service map feedback faster

### `opensearch/config/opensearch.yml`

Controls OpenSearch node behavior:

- cluster name
- node name
- bind address
- HTTP port
- single-node discovery
- demo security SSL configuration

### `opensearch/config/opensearch_dashboards.yml`

Controls Dashboards behavior:

- Dashboards-to-OpenSearch connection
- the `kibanaserver` service account
- workspace mode
- multitenancy
- data source feature flags
- default landing route
- default UI settings at startup

### `.env`

Stores local values that should not be hardcoded:

- `OPENSEARCH_ADMIN_PASSWORD`

### `otel-collector/config.yml`

Controls how traces leave the collector:

- the OTLP receiver ports for applications
- the exporter to Tempo
- the exporter to Data Prepper

In this repository, traces fan out to:

- `tempo:4317`
- `data-prepper:21890`

## What To Change In The UI Vs In Files

### Better changed in the UI

- creating or editing workspaces
- building dashboards
- building visualizations
- using Discover
- managing saved objects
- changing advanced settings that are not locked by config

### Better changed in files

- image and container version
- ports or networks
- mount paths
- ingest pipeline behavior in Data Prepper
- the Dashboards-to-OpenSearch security connection
- feature flags such as `workspace.enabled`
- startup-level global settings such as `defaultRoute`

## Running The OpenSearch Stack

Run from the repository root:

```bash
podman-compose -f compose/opensearch/compose.yaml up -d
```

If you want traces to show up in the `Observability` workspace, also start the tracing stack:

```bash
podman-compose -f compose/trace/compose.yaml up -d
```

Stop the stack:

```bash
podman-compose -f compose/opensearch/compose.yaml down
```

## Basic Verification

### Check OpenSearch

```bash
curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" https://localhost:9200
```

### Check Dashboards login redirect

```bash
curl -I http://localhost:5601
```

Expected result:

- redirect to `/app/login` when not authenticated

### Check Data Prepper

```bash
curl -s http://localhost:4900/list
```

Expected result:

- a pipeline list containing `trace-entry-pipeline`
- `trace-raw-pipeline`
- `trace-service-map-pipeline`

### Check trace analytics documents

```bash
curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" \
  https://localhost:9200/otel-v1-apm-span-000001/_count
```

Expected result:

- `count` greater than `0` after traces are sent through the collector

### Check workspace list

```bash
curl -sS -u "admin:$OPENSEARCH_ADMIN_PASSWORD" \
  -H 'osd-xsrf: true' \
  -H 'content-type: application/json' \
  -X POST http://localhost:5601/api/workspaces/_list \
  -d '{}'
```

## Troubleshooting

### Image pull fails with `docker.opensearch.org: no such host`

That is usually not a local single-node config problem. It is a registry source or DNS reachability problem.

Use an active image source such as:

- `docker.io/opensearchproject/opensearch:<version>`
- `docker.io/opensearchproject/opensearch-dashboards:<version>`

### Dashboards cannot connect to OpenSearch

Check:

- `opensearch.hosts`
- `opensearch.username`
- `opensearch.password`
- SSL settings in `opensearch.yml` and `opensearch_dashboards.yml`

If the `kibanaserver` account is wrong or does not match the OpenSearch security configuration, Dashboards can stay up as a container while still failing to talk to the backend.

### Data Prepper API is up but trace indices stay empty

Check:

- `compose/trace/compose.yaml` is running, not only the OpenSearch stack
- `otel-collector/config.yml` still exports traces to `data-prepper:21890`
- `curl -s http://localhost:4900/list` shows the three trace pipelines
- `podman logs observability-data-prepper` does not show OpenSearch sink write errors

For fast local feedback, this repository intentionally keeps:

- `trace_flush_interval: 5`
- `service_map.window_duration: 10`

If you increase those values, traces and service maps can take much longer to appear.

### Workspace API fails on `permissions` mapping

In security and multitenancy mode, Dashboards can create a tenant-specific index such as `.kibana_<hash>_admin_1`.

If workspace creation fails with an error like:

```text
strict_dynamic_mapping_exception
mapping set to strict, dynamic introduction of [permissions] is not allowed
```

it usually means the active tenant index is missing the mapping required by workspace ACL fields.

Suggested checks:

1. inspect the `.kibana*` aliases
2. identify the active tenant index
3. compare that tenant mapping with the global `.kibana` mapping
4. add missing fields such as `permissions` and `workspaces`

Example alias check:

```bash
curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" \
  https://localhost:9200/_alias/.kibana*?pretty
```

Once you know the active tenant index name, the mapping can be updated manually. This is stateful operational behavior, so it can reappear after a full tenant reset.

## Summary

Quick memory aid:

- OpenSearch: stores and queries data
- Dashboards: UI for using OpenSearch
- Data Prepper: installed ingest pipeline for OpenSearch trace analytics
- `kibanaserver`: internal Dashboards service account, not a human user
- `Observability` workspace: logs, metrics, traces, applications
- `Security` workspace: security analytics and related views
