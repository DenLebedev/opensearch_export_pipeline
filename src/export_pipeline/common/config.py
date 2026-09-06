"""Application configuration loaded from Lambda environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when required application configuration is invalid."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise ConfigurationError(
            f"Environment variable {name} is required"
        )

    return value


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name} must be an integer"
        ) from exc

    if value <= 0:
        raise ConfigurationError(
            f"Environment variable {name} must be greater than zero"
        )

    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings shared by the Lambda functions."""

    opensearch_endpoint: str
    export_bucket: str
    export_table: str
    aws_region: str

    pit_keep_alive: str = "10m"
    default_page_size: int = 1_000
    default_slice_count: int = 16
    max_pages_per_invocation: int = 5
    lambda_safety_margin_ms: int = 30_000

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            opensearch_endpoint=_required(
                "OPENSEARCH_ENDPOINT"
            ).rstrip("/"),
            export_bucket=_required("EXPORT_BUCKET"),
            export_table=_required("EXPORT_TABLE"),
            aws_region=os.getenv(
                "AWS_REGION",
                "eu-central-1",
            ),
            pit_keep_alive=os.getenv(
                "PIT_KEEP_ALIVE",
                "10m",
            ),
            default_page_size=_positive_int(
                "DEFAULT_PAGE_SIZE",
                1_000,
            ),
            default_slice_count=_positive_int(
                "DEFAULT_SLICE_COUNT",
                16,
            ),
            max_pages_per_invocation=_positive_int(
                "MAX_PAGES_PER_INVOCATION",
                5,
            ),
            lambda_safety_margin_ms=_positive_int(
                "LAMBDA_SAFETY_MARGIN_MS",
                30_000,
            ),
        )