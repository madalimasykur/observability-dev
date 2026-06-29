# Order Sample Service

Service HTTP sederhana untuk demo observability lokal:

- traces -> OpenTelemetry Collector -> Tempo
- metrics -> Prometheus scrape `/metrics`
- logs -> stdout service + file lokal -> Promtail -> Loki

## Endpoints

- `GET /healthz`
- `GET /metrics`
- `POST /orders`
- `POST /demo/orders?count=20`

## Run dari host

```bash
cd order-sample-service

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

OTEL_EXPORTER_OTLP_ENDPOINT=localhost:4317 ./run.sh
```

Log file akan ditulis ke `logs/order-sample-service.log` di root repo supaya bisa di-scrape oleh Promtail.
Format log sekarang JSON lines supaya lebih mudah di-parse di Loki dan tool analisis lain.

Generate sample traffic:

```bash
curl -X POST http://localhost:8010/demo/orders?count=20
```

Atau kirim 1 order sederhana:

```bash
curl -X POST http://localhost:8010/orders \
  -H 'content-type: application/json' \
  -d '{
    "customer_id": "CUST-2001",
    "product_id": "SKU-MONITOR-27",
    "quantity": 1,
    "amount": 349000
  }'
```

## Run dari container

```bash
cd order-sample-service

podman run --rm \
  --network observability \
  -p 8010:8010 \
  -v "$PWD:/app:Z" \
  -w /app \
  docker.io/python:3.12-slim \
  sh -c '
    pip install -r requirements.txt &&
    OTEL_EXPORTER_OTLP_ENDPOINT=otel-collector:4317 ./run.sh
  '
```

## Query di Grafana Tempo

```traceql
{ resource.service.name = "order-sample-service" }
```

```traceql
{ resource.service.name = "payment-service" }
```

```traceql
{ span.order.id = "ORD-20260629-0001" }
```

## Query di Prometheus

```promql
order_sample_service_orders_total
```

```promql
rate(order_sample_service_http_requests_total[5m])
```

```promql
histogram_quantile(0.95, sum(rate(order_sample_service_http_request_duration_seconds_bucket[5m])) by (le))
```

## Query di Loki

```logql
{service_name="order-sample-service"}
```

```logql
{service_name="order-sample-service"} | json
```

```logql
{service_name="order-sample-service", event="order_created"}
```

## Catatan Loki

Stack ini masih memakai Loki `2.9.8`. Karena itu fitur UI Grafana untuk JSON field filtering memang masih read-only jika muncul pesan:

`JSON filtering requires Loki 3.5.0`

Meski begitu, log JSON tetap bisa diparse sekarang dengan LogQL memakai `| json`.
