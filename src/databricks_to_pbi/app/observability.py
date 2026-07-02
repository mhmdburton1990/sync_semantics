"""Structlog + Prometheus metric registry."""

from __future__ import annotations

import logging
import sys

import structlog
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "REGISTRY",
    "cache_hit_ratio",
    "configure_logging",
    "llm_tokens_used",
    "manual_review_objects",
    "render_metrics",
    "sync_duration_seconds",
    "sync_runs_total",
    "translations_total",
]


REGISTRY = CollectorRegistry()


sync_runs_total = Counter(
    "sync_runs_total",
    "Total sync runs grouped by mode/delivery/outcome.",
    ["mode", "delivery", "outcome"],
    registry=REGISTRY,
)

sync_duration_seconds = Histogram(
    "sync_duration_seconds",
    "Sync stage duration in seconds.",
    ["stage"],
    registry=REGISTRY,
)

translations_total = Counter(
    "translations_total",
    "SQL->DAX translations grouped by method (rule/cache/llm/placeholder).",
    ["method"],
    registry=REGISTRY,
)

cache_hit_ratio = Gauge(
    "cache_hit_ratio",
    "Last run's SQL->DAX cache hit ratio (0.0-1.0).",
    registry=REGISTRY,
)

llm_tokens_used = Counter(
    "llm_tokens_used",
    "Anthropic tokens consumed grouped by kind (input/output).",
    ["kind"],
    registry=REGISTRY,
)

manual_review_objects = Gauge(
    "manual_review_objects",
    "Number of objects flagged for manual review by the last run.",
    registry=REGISTRY,
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)


def configure_logging() -> None:
    """JSON structured logging via structlog -> stdout (Databricks Apps captures)."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
