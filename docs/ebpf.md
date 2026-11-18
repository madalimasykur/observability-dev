# eBPF Instrumentation

This repository uses OpenTelemetry eBPF Instrumentation (OBI) as an optional
zero-code source of HTTP and gRPC traces and metrics. OBI sends OTLP/gRPC to the
existing OpenTelemetry Collector; it does not deploy a second collector.

## Data flow

```text
Linux process -> eBPF probes -> OBI -> OTLP/gRPC :4317
    -> OpenTelemetry Collector -> Tempo (traces)
                               -> Prometheus exporter (metrics)
```

The existing collector already exposes OTLP/gRPC on `4317` and OTLP/HTTP on
`4318`, so no collector pipeline change is required.

## Files

- `obi/config.yml`: standalone OBI Config v2.
- `otel-collector/config.yml`: the existing OTLP receiver and telemetry
  pipelines used by OBI.

OBI intentionally runs as a native host process. It is not part of the rootless
Podman Compose stack because eBPF requires host-kernel access that a rootless
container cannot provide reliably. The repository also does not add a
persistently privileged container.

## Requirements

- Linux `amd64` or `arm64`.
- Linux kernel `5.8+`, or a RHEL-family `4.18+` kernel with the required eBPF
  backports.
- BTF available at `/sys/kernel/btf/vmlinux`.
- Root or the Linux capabilities required by the enabled OBI features.
- The observability Collector running and reachable on host port `4317`.

Check the host before starting OBI:

```bash
uname -r
uname -m
test -r /sys/kernel/btf/vmlinux && echo "BTF available"
```

## Start the existing Collector

Run commands from the repository root because the Compose file uses `${PWD}`
for bind mounts.

```bash
podman-compose -f compose/observability/compose.yaml \
  up -d prometheus loki tempo otel-collector grafana
```

The Collector publishes OTLP/gRPC on host port `4317`. The OBI configuration
uses `http://127.0.0.1:4317` by default.

## Install OBI

Download the current release archive for the host architecture from the OBI
release page, verify its checksum, and install the binary. The following example
pins the version used when this configuration was added:

```bash
OBI_VERSION=1.0.0

case "$(uname -m)" in
  x86_64) OBI_ARCH=amd64 ;;
  aarch64|arm64) OBI_ARCH=arm64 ;;
  *) echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
esac

wget "https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/releases/download/v${OBI_VERSION}/obi-v${OBI_VERSION}-linux-${OBI_ARCH}.tar.gz"
wget "https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/releases/download/v${OBI_VERSION}/SHA256SUMS"

sha256sum -c SHA256SUMS --ignore-missing
tar -xzf "obi-v${OBI_VERSION}-linux-${OBI_ARCH}.tar.gz"
sudo install -m 0755 obi /usr/local/bin/obi
obi --version
```

Do not install or execute the archive if checksum verification fails.

## Configure the target

The default configuration captures HTTP and gRPC traffic from processes that
listen on ports `9581`, `8080`, or `5000`. OBI derives the service identity from
the target process or container metadata. Override the capture and export
values at runtime:

```bash
export OBI_OPEN_PORTS=9581,8080,5000
export OBI_OTLP_ENDPOINT=http://127.0.0.1:4317
```

`OBI_OPEN_PORTS` accepts comma-separated ports and ranges, for example
`9581,8080,5000`. Keep the selection narrow to avoid collecting unrelated
host processes. For containerized applications, use the port opened by the
application inside the container, not the published host port. For example,
host port `5580` maps to SFTPGo port `8080`, and host port `5100` maps to Zot
port `5000`.

## Validate and run OBI

Validate the file without attaching probes:

```bash
OBI_OPEN_PORTS=9581,8080,5000 \
OBI_OTLP_ENDPOINT=http://127.0.0.1:4317 \
obi config validate ./obi/config.yml
```

For a local test, run OBI with elevated privileges:

```bash
sudo env \
  OBI_OPEN_PORTS=9581,8080,5000 \
  OBI_OTLP_ENDPOINT=http://127.0.0.1:4317 \
  obi --config=./obi/config.yml
```

For a long-running or production installation, create a dedicated service and
assign only the capabilities required by the OBI features in use. Do not grant
full root access or run a privileged container by default.

## Generate test telemetry

Generate traffic against the selected services through their host-published
endpoints:

```bash
curl http://127.0.0.1:9581/
```

In another terminal:

```bash
curl http://127.0.0.1:5580/

curl http://127.0.0.1:5100/v2/
```

Do not use `order-sample-service` as the first OBI target without disabling its
SDK instrumentation. That service already exports hand-written spans, so
explicitly selecting it in OBI can create overlapping telemetry.

## Verify the pipeline

Check that the Collector is listening and inspect its logs:

```bash
ss -lnt | grep ':4317'
podman logs observability-otel-collector
```

In Grafana Explore, select Tempo and query the detected target name, for example:

```traceql
{ resource.service.name = "ttyd" }
```

Use `sftpgo` or `zot` when querying those container workloads. Existing spans
created before removing the global service name can still be labeled
`ebpf-service`; only new telemetry uses the derived target identity.

OBI exports metrics through the same Collector. The Collector exposes converted
Prometheus metrics on `9464`, which the existing Prometheus configuration
scrapes.

## Endpoint selection

| OBI deployment | OTLP endpoint |
| --- | --- |
| Native process on this host | `http://127.0.0.1:4317` |
| Container on the `observability` network | `http://otel-collector:4317` |
| Kubernetes workload | `http://otel-collector.observability.svc.cluster.local:4317` |

OTLP/gRPC endpoints do not use `/v1/traces` or `/v1/metrics` URL paths.

## Troubleshooting

### `operation not permitted`

Confirm kernel support and inspect host security controls:

```bash
sudo bpftool feature probe kernel
```

SELinux, kernel lockdown, seccomp, and missing Linux capabilities can prevent
OBI from attaching probes.

### OBI starts but exports nothing

1. Confirm the target process is listening on `OBI_OPEN_PORTS`.
2. Generate traffic after OBI starts.
3. Confirm the protocol/runtime is supported.
4. Check that host port `4317` is listening.

```bash
ss -lnt | grep ':4317'
ss -lnt | grep -E ':(9581|5580|5100)'
```

### Collector is unreachable

Confirm the existing Collector is running:

```bash
podman ps --filter name=observability-otel-collector
podman logs observability-otel-collector
```

## Production notes

- Use the minimum documented Linux capabilities instead of unrestricted root.
- Use TLS or mTLS when OBI and the Collector communicate across hosts.
- Restrict capture rules by port, executable, container, or Kubernetes metadata.
- Review HTTP paths and database or messaging attributes before exporting data
  outside the host.
- Use route normalization and Collector filtering to control cardinality.
- eBPF instrumentation does not replace SDK instrumentation for business spans,
  custom attributes, or application-specific events.

## References

- [OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/docs/zero-code/obi/)
- [Run OBI as a standalone process](https://opentelemetry.io/docs/zero-code/obi/setup/standalone/)
- [OBI Config v2](https://opentelemetry.io/docs/zero-code/obi/configure/config-v2/)
- [OBI security and capabilities](https://opentelemetry.io/docs/zero-code/obi/security/)
