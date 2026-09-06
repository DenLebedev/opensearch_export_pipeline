import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parents[2]
STATE_MACHINES_DIRECTORY = (
    PROJECT_ROOT / "statemachines"
)


def load_template(name: str) -> dict[str, Any]:
    template_path = (
        STATE_MACHINES_DIRECTORY / name
    )

    content = template_path.read_text(
        encoding="utf-8"
    )

    replacements = {
        "${export_page_group_lambda_arn}": (
            "arn:aws:lambda:eu-central-1:"
            "123456789012:function:export-page-group"
        ),
        "${initialize_export_lambda_arn}": (
            "arn:aws:lambda:eu-central-1:"
            "123456789012:function:initialize-export"
        ),
        "${cleanup_export_lambda_arn}": (
            "arn:aws:lambda:eu-central-1:"
            "123456789012:function:cleanup-export"
        ),
        "${finalize_export_lambda_arn}": (
            "arn:aws:lambda:eu-central-1:"
            "123456789012:function:finalize-export"
        ),
        "${slice_state_machine_arn}": (
            "arn:aws:states:eu-central-1:"
            "123456789012:stateMachine:slice-export"
        ),
        "${max_concurrency}": "4",
    }

    for placeholder, value in replacements.items():
        content = content.replace(
            placeholder,
            value,
        )

    return json.loads(content)


def assert_state_target_exists(
    definition: dict[str, Any],
    state_name: str,
    target_name: str,
) -> None:
    states = definition["States"]

    assert state_name in states
    assert target_name in states


def test_slice_template_is_valid_json() -> None:
    definition = load_template(
        "slice.asl.json.tftpl"
    )

    assert definition["StartAt"] == (
        "ExportPageGroup"
    )

    assert set(definition["States"]) == {
        "ExportPageGroup",
        "HasMorePages",
        "SliceCompleted",
    }


def test_slice_workflow_contains_pagination_loop() -> None:
    definition = load_template(
        "slice.asl.json.tftpl"
    )

    states = definition["States"]
    choice = states["HasMorePages"]

    assert (
        states["ExportPageGroup"]["Next"]
        == "HasMorePages"
    )
    assert (
        choice["Choices"][0]["Next"]
        == "ExportPageGroup"
    )
    assert (
        choice["Default"]
        == "SliceCompleted"
    )


def test_slice_workflow_retries_temporary_errors() -> None:
    definition = load_template(
        "slice.asl.json.tftpl"
    )

    retry_rules = (
        definition["States"]["ExportPageGroup"][
            "Retry"
        ]
    )

    retried_errors = {
        error
        for rule in retry_rules
        for error in rule["ErrorEquals"]
    }

    assert "TemporaryOpenSearchError" in (
        retried_errors
    )
    assert "Lambda.TooManyRequestsException" in (
        retried_errors
    )


def test_parent_template_is_valid_json() -> None:
    definition = load_template(
        "parent.asl.json.tftpl"
    )

    assert definition["StartAt"] == (
        "InitializeExport"
    )

    assert "ExportSlices" in definition["States"]
    assert "FinalizeExport" in definition["States"]
    assert "CleanupFailedExport" in (
        definition["States"]
    )


def test_parent_uses_distributed_map() -> None:
    definition = load_template(
        "parent.asl.json.tftpl"
    )

    export_slices = (
        definition["States"]["ExportSlices"]
    )

    processor_config = (
        export_slices["ItemProcessor"][
            "ProcessorConfig"
        ]
    )

    assert export_slices["Type"] == "Map"
    assert processor_config["Mode"] == "DISTRIBUTED"
    assert (
        processor_config["ExecutionType"]
        == "STANDARD"
    )
    assert export_slices["MaxConcurrency"] == 4


def test_parent_starts_slice_state_machine() -> None:
    definition = load_template(
        "parent.asl.json.tftpl"
    )

    start_slice = (
        definition["States"]["ExportSlices"][
            "ItemProcessor"
        ]["States"]["StartSliceWorkflow"]
    )

    assert start_slice["Resource"] == (
        "arn:aws:states:::"
        "states:startExecution.sync:2"
    )


def test_parent_handles_existing_export() -> None:
    definition = load_template(
        "parent.asl.json.tftpl"
    )

    choice = definition["States"][
        "ExportAlreadyExists"
    ]

    assert (
        choice["Choices"][0]["Next"]
        == "ReturnExistingExport"
    )


def test_parent_has_success_and_failure_cleanup() -> None:
    definition = load_template(
        "parent.asl.json.tftpl"
    )

    states = definition["States"]

    assert (
        states["ExportSlices"]["Next"]
        == "CleanupSuccessfulExport"
    )

    assert (
        states["ExportSlices"]["Catch"][0]["Next"]
        == "CleanupFailedExport"
    )

    assert (
        states["FinalizeExport"]["Catch"][0][
            "Next"
        ]
        == "CleanupFailedExport"
    )