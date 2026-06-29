import itertools
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field


OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
SERVICE_NAME = "order-sample-service"
SERVICE_VERSION = "0.2.0"
ORDER_SEQUENCE = itertools.count(int(os.getenv("ORDER_SEQUENCE_START", "1")))
APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
LOG_DIR = Path(os.getenv("ORDER_SAMPLE_LOG_DIR", str(REPO_ROOT / "logs")))
LOG_FILE = Path(os.getenv("ORDER_SAMPLE_LOG_FILE", str(LOG_DIR / f"{SERVICE_NAME}.log")))
LOG_DIR.mkdir(parents=True, exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service_name": SERVICE_NAME,
            "message": record.getMessage(),
        }

        extra_payload = getattr(record, "payload", None)
        if isinstance(extra_payload, dict):
            payload.update(extra_payload)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


stream_handler = logging.StreamHandler()
stream_handler.setFormatter(JsonFormatter())

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(JsonFormatter())

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    handlers=[stream_handler, file_handler],
    force=True,
)
logger = logging.getLogger(SERVICE_NAME)


HTTP_REQUESTS = Counter(
    "order_sample_service_http_requests_total",
    "Total HTTP requests handled by the order sample service.",
    ["route", "method", "status"],
)
ORDER_RESULTS = Counter(
    "order_sample_service_orders_total",
    "Total processed orders grouped by result.",
    ["result"],
)
HTTP_DURATION = Histogram(
    "order_sample_service_http_request_duration_seconds",
    "HTTP request duration for the order sample service.",
    ["route", "method"],
)


class OrderRequest(BaseModel):
    customer_id: str | None = None
    product_id: str | None = None
    quantity: int = Field(default=1, ge=1, le=5)
    amount: int | None = Field(default=None, ge=1000)


def sleep_ms(min_ms: int, max_ms: int) -> None:
    time.sleep(random.uniform(min_ms, max_ms) / 1000)


def build_tracer(service_name: str):
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "demo-commerce",
            "deployment.environment": "local-dev",
            "service.version": SERVICE_VERSION,
        }
    )

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider, provider.get_tracer(service_name)


providers: list[TracerProvider] = []

order_provider, order_tracer = build_tracer(SERVICE_NAME)
inventory_provider, inventory_tracer = build_tracer("inventory-service")
payment_provider, payment_tracer = build_tracer("payment-service")
notification_provider, notification_tracer = build_tracer("notification-service")
db_provider, db_tracer = build_tracer("postgres-db")
broker_provider, broker_tracer = build_tracer("kafka-broker")

providers.extend(
    [
        order_provider,
        inventory_provider,
        payment_provider,
        notification_provider,
        db_provider,
        broker_provider,
    ]
)


def current_trace_fields() -> dict[str, str]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context or not span_context.is_valid:
        return {"trace_id": "-", "span_id": "-"}

    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        **fields,
        **current_trace_fields(),
    }
    logger.info(event, extra={"payload": payload})


def build_order_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}

    return {
        "customer_id": payload.get("customer_id") or f"CUST-{random.randint(1000, 9999)}",
        "product_id": payload.get("product_id")
        or random.choice(
            [
                "SKU-MACBOOK-AIR",
                "SKU-THINKPAD-X1",
                "SKU-MECHA-KEYBOARD",
                "SKU-MONITOR-27",
            ]
        ),
        "quantity": int(payload.get("quantity", 1)),
        "amount": int(payload.get("amount") or random.choice([199000, 349000, 1250000, 18999000])),
    }


def reserve_inventory(parent_span, order_id: str, product_id: str, quantity: int) -> bool:
    parent_ctx = trace.set_span_in_context(parent_span)

    with order_tracer.start_as_current_span(
        "HTTP POST /inventory/reservations",
        context=parent_ctx,
        kind=SpanKind.CLIENT,
        attributes={
            "http.request.method": "POST",
            "url.full": "http://inventory-service:8080/inventory/reservations",
            "server.address": "inventory-service",
            "server.port": 8080,
            "order.id": order_id,
            "product.id": product_id,
            "item.quantity": quantity,
        },
    ) as client_span:
        sleep_ms(10, 30)

        server_ctx = trace.set_span_in_context(client_span)

        with inventory_tracer.start_as_current_span(
            "POST /inventory/reservations",
            context=server_ctx,
            kind=SpanKind.SERVER,
            attributes={
                "http.route": "/inventory/reservations",
                "http.request.method": "POST",
                "order.id": order_id,
                "product.id": product_id,
                "item.quantity": quantity,
            },
        ) as server_span:
            sleep_ms(15, 40)

            with db_tracer.start_as_current_span(
                "SELECT inventory_stock",
                context=trace.set_span_in_context(server_span),
                kind=SpanKind.CLIENT,
                attributes={
                    "db.system.name": "postgresql",
                    "db.namespace": "inventory",
                    "db.operation.name": "SELECT",
                    "db.query.text": "SELECT available_qty FROM inventory_stock WHERE product_id = $1",
                    "product.id": product_id,
                },
            ):
                sleep_ms(8, 25)

            with db_tracer.start_as_current_span(
                "UPDATE inventory_stock",
                context=trace.set_span_in_context(server_span),
                kind=SpanKind.CLIENT,
                attributes={
                    "db.system.name": "postgresql",
                    "db.namespace": "inventory",
                    "db.operation.name": "UPDATE",
                    "db.query.text": "UPDATE inventory_stock SET reserved_qty = reserved_qty + $1 WHERE product_id = $2",
                    "product.id": product_id,
                    "item.quantity": quantity,
                },
            ):
                sleep_ms(10, 30)

            server_span.set_attribute("inventory.reservation.status", "reserved")
            return True


def authorize_payment(parent_span, order_id: str, amount: Decimal) -> bool:
    parent_ctx = trace.set_span_in_context(parent_span)

    with order_tracer.start_as_current_span(
        "HTTP POST /payments/authorize",
        context=parent_ctx,
        kind=SpanKind.CLIENT,
        attributes={
            "http.request.method": "POST",
            "url.full": "http://payment-service:8080/payments/authorize",
            "server.address": "payment-service",
            "server.port": 8080,
            "order.id": order_id,
            "payment.amount": float(amount),
            "payment.currency": "IDR",
        },
    ) as client_span:
        sleep_ms(15, 35)

        with payment_tracer.start_as_current_span(
            "POST /payments/authorize",
            context=trace.set_span_in_context(client_span),
            kind=SpanKind.SERVER,
            attributes={
                "http.route": "/payments/authorize",
                "http.request.method": "POST",
                "order.id": order_id,
                "payment.amount": float(amount),
                "payment.currency": "IDR",
                "payment.method": "virtual_account",
            },
        ) as server_span:
            sleep_ms(20, 50)

            with payment_tracer.start_as_current_span(
                "HTTP POST /gateway/charge",
                context=trace.set_span_in_context(server_span),
                kind=SpanKind.CLIENT,
                attributes={
                    "http.request.method": "POST",
                    "url.full": "https://dummy-payment-gateway.local/charge",
                    "server.address": "dummy-payment-gateway.local",
                    "payment.gateway": "dummy-gateway",
                    "payment.amount": float(amount),
                    "payment.currency": "IDR",
                },
            ) as gateway_span:
                sleep_ms(40, 120)

                if random.random() < 0.08:
                    gateway_span.set_status(Status(StatusCode.ERROR, "payment gateway timeout"))
                    gateway_span.set_attribute("error.type", "gateway_timeout")
                    return False

                gateway_span.set_attribute("payment.gateway.status", "approved")

            with db_tracer.start_as_current_span(
                "INSERT payment_authorization",
                context=trace.set_span_in_context(server_span),
                kind=SpanKind.CLIENT,
                attributes={
                    "db.system.name": "postgresql",
                    "db.namespace": "payment",
                    "db.operation.name": "INSERT",
                    "db.query.text": "INSERT INTO payment_authorization(order_id, amount, status) VALUES($1, $2, $3)",
                    "order.id": order_id,
                },
            ):
                sleep_ms(10, 25)

            server_span.set_attribute("payment.authorization.status", "approved")
            return True


def persist_order(parent_span, order_id: str, customer_id: str, amount: Decimal) -> None:
    with db_tracer.start_as_current_span(
        "INSERT orders",
        context=trace.set_span_in_context(parent_span),
        kind=SpanKind.CLIENT,
        attributes={
            "db.system.name": "postgresql",
            "db.namespace": "orders",
            "db.operation.name": "INSERT",
            "db.query.text": "INSERT INTO orders(order_id, customer_id, total_amount, status) VALUES($1, $2, $3, $4)",
            "order.id": order_id,
            "customer.id": customer_id,
            "order.amount": float(amount),
        },
    ):
        sleep_ms(15, 35)


def publish_order_created(parent_span, order_id: str) -> None:
    with order_tracer.start_as_current_span(
        "kafka publish order.created",
        context=trace.set_span_in_context(parent_span),
        kind=SpanKind.PRODUCER,
        attributes={
            "messaging.system": "kafka",
            "messaging.operation.name": "publish",
            "messaging.destination.name": "order.created",
            "messaging.kafka.message.key": order_id,
            "order.id": order_id,
        },
    ) as producer_span:
        sleep_ms(8, 20)

        with broker_tracer.start_as_current_span(
            "kafka append order.created",
            context=trace.set_span_in_context(producer_span),
            kind=SpanKind.SERVER,
            attributes={
                "messaging.system": "kafka",
                "messaging.destination.name": "order.created",
                "messaging.operation.name": "append",
                "order.id": order_id,
            },
        ):
            sleep_ms(5, 15)


def send_notification(parent_span, order_id: str, customer_id: str) -> None:
    with broker_tracer.start_as_current_span(
        "kafka consume order.created",
        context=trace.set_span_in_context(parent_span),
        kind=SpanKind.CONSUMER,
        attributes={
            "messaging.system": "kafka",
            "messaging.operation.name": "process",
            "messaging.destination.name": "order.created",
            "order.id": order_id,
        },
    ) as consumer_span:
        sleep_ms(5, 15)

        with notification_tracer.start_as_current_span(
            "POST /notifications/order-confirmation",
            context=trace.set_span_in_context(consumer_span),
            kind=SpanKind.SERVER,
            attributes={
                "http.route": "/notifications/order-confirmation",
                "http.request.method": "POST",
                "order.id": order_id,
                "customer.id": customer_id,
                "notification.channel": "email",
            },
        ) as notification_span:
            sleep_ms(20, 60)

            with notification_tracer.start_as_current_span(
                "SMTP send order confirmation",
                context=trace.set_span_in_context(notification_span),
                kind=SpanKind.CLIENT,
                attributes={
                    "server.address": "smtp.local",
                    "server.port": 587,
                    "notification.channel": "email",
                    "order.id": order_id,
                },
            ):
                sleep_ms(30, 80)


def create_order(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    order_number = next(ORDER_SEQUENCE)
    order_id = f"ORD-{time.strftime('%Y%m%d')}-{order_number:04d}"
    order = build_order_payload(payload)
    amount = Decimal(order["amount"])

    with order_tracer.start_as_current_span(
        "POST /orders",
        kind=SpanKind.SERVER,
        attributes={
            "http.route": "/orders",
            "http.request.method": "POST",
            "user.id": order["customer_id"],
            "customer.id": order["customer_id"],
            "order.id": order_id,
            "product.id": order["product_id"],
            "item.quantity": order["quantity"],
            "order.amount": float(amount),
            "order.currency": "IDR",
        },
    ) as root_span:
        sleep_ms(20, 50)
        log_event(
            "order_received",
            order_id=order_id,
            customer_id=order["customer_id"],
            product_id=order["product_id"],
            quantity=order["quantity"],
            amount=order["amount"],
        )

        if not reserve_inventory(root_span, order_id, order["product_id"], order["quantity"]):
            root_span.set_status(Status(StatusCode.ERROR, "inventory reservation failed"))
            root_span.set_attribute("order.status", "FAILED_INVENTORY")
            log_event("order_failed_inventory", order_id=order_id)
            return {"order_id": order_id, "status": "FAILED_INVENTORY"}

        if not authorize_payment(root_span, order_id, amount):
            root_span.set_status(Status(StatusCode.ERROR, "payment authorization failed"))
            root_span.set_attribute("order.status", "FAILED_PAYMENT")
            log_event("order_failed_payment", order_id=order_id)
            return {"order_id": order_id, "status": "FAILED_PAYMENT"}

        persist_order(root_span, order_id, order["customer_id"], amount)
        publish_order_created(root_span, order_id)
        send_notification(root_span, order_id, order["customer_id"])

        root_span.set_attribute("http.response.status_code", 201)
        root_span.set_attribute("order.status", "CREATED")
        root_span.set_status(Status(StatusCode.OK))

        log_event("order_created", order_id=order_id, customer_id=order["customer_id"])
        return {
            "order_id": order_id,
            "status": "CREATED",
            "customer_id": order["customer_id"],
            "product_id": order["product_id"],
            "quantity": order["quantity"],
            "amount": order["amount"],
        }


def request_model_dump(model: OrderRequest) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    log_event("service_started", otlp_endpoint=OTLP_ENDPOINT, log_file=str(LOG_FILE))
    yield
    log_event("service_stopping")
    for provider in providers:
        provider.force_flush()
        provider.shutdown()


app = FastAPI(title="Order Sample Service", version=SERVICE_VERSION, lifespan=lifespan)


@app.get("/")
def index() -> dict[str, str]:
    return {
        "service": SERVICE_NAME,
        "status": "ok",
        "docs": "/docs",
        "healthz": "/healthz",
        "metrics": "/metrics",
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/orders")
def create_order_endpoint(order: OrderRequest | None = Body(default=None)) -> JSONResponse:
    started_at = time.perf_counter()
    route = "/orders"
    method = "POST"

    try:
        result = create_order(request_model_dump(order) if order else None)
        status_code = 201 if result["status"] == "CREATED" else 502
        ORDER_RESULTS.labels(result=result["status"]).inc()
        HTTP_REQUESTS.labels(route=route, method=method, status=str(status_code)).inc()
        return JSONResponse(status_code=status_code, content=result)
    except Exception as exc:
        HTTP_REQUESTS.labels(route=route, method=method, status="500").inc()
        ORDER_RESULTS.labels(result="ERROR").inc()
        logger.exception(
            "order_request_failed",
            extra={"payload": {"event": "order_request_failed", "error": str(exc)}},
        )
        raise HTTPException(status_code=500, detail="failed to create demo order") from exc
    finally:
        HTTP_DURATION.labels(route=route, method=method).observe(time.perf_counter() - started_at)


@app.post("/demo/orders")
def create_demo_orders(count: int = 10) -> dict[str, Any]:
    if count < 1 or count > 100:
        raise HTTPException(status_code=400, detail="count must be between 1 and 100")

    started_at = time.perf_counter()
    route = "/demo/orders"
    method = "POST"
    results: list[dict[str, Any]] = []

    try:
        for _ in range(count):
            results.append(create_order())
            sleep_ms(50, 150)

        summary: dict[str, int] = {}
        for item in results:
            summary[item["status"]] = summary.get(item["status"], 0) + 1

        HTTP_REQUESTS.labels(route=route, method=method, status="200").inc()
        for status, total in summary.items():
            ORDER_RESULTS.labels(result=status).inc(total)

        return {"count": count, "summary": summary, "orders": results}
    finally:
        HTTP_DURATION.labels(route=route, method=method).observe(time.perf_counter() - started_at)
