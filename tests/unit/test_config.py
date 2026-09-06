import pytest

from export_pipeline.common.config import (
    ConfigurationError,
    Settings,
)


def test_loads_required_settings_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OPENSEARCH_ENDPOINT",
        "https://search.example.com/",
    )
    monkeypatch.setenv(
        "EXPORT_BUCKET",
        "exports-bucket",
    )
    monkeypatch.setenv(
        "EXPORT_TABLE",
        "export-jobs",
    )
    monkeypatch.setenv(
        "AWS_REGION",
        "eu-west-1",
    )

    settings = Settings.from_env()

    assert (
        settings.opensearch_endpoint
        == "https://search.example.com"
    )
    assert settings.export_bucket == "exports-bucket"
    assert settings.export_table == "export-jobs"
    assert settings.aws_region == "eu-west-1"
    assert settings.default_page_size == 1_000
    assert settings.default_slice_count == 16


def test_rejects_missing_required_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "OPENSEARCH_ENDPOINT",
        raising=False,
    )
    monkeypatch.setenv(
        "EXPORT_BUCKET",
        "exports-bucket",
    )
    monkeypatch.setenv(
        "EXPORT_TABLE",
        "export-jobs",
    )

    with pytest.raises(
        ConfigurationError,
        match="OPENSEARCH_ENDPOINT",
    ):
        Settings.from_env()


def test_rejects_non_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OPENSEARCH_ENDPOINT",
        "https://search.example.com",
    )
    monkeypatch.setenv(
        "EXPORT_BUCKET",
        "exports-bucket",
    )
    monkeypatch.setenv(
        "EXPORT_TABLE",
        "export-jobs",
    )
    monkeypatch.setenv(
        "DEFAULT_PAGE_SIZE",
        "0",
    )

    with pytest.raises(
        ConfigurationError,
        match="greater than zero",
    ):
        Settings.from_env()