locals {
  name_prefix = "${var.project_name}-${var.environment}"

  export_table_name = coalesce(
    var.export_table_name,
    "${local.name_prefix}-jobs"
  )

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Component   = "OpenSearchExport"
    },
    var.additional_tags
  )

  lambda_names = {
    initialize = "${local.name_prefix}-initialize"
    worker     = "${local.name_prefix}-page-worker"
    cleanup    = "${local.name_prefix}-cleanup"
    finalize   = "${local.name_prefix}-finalize"
  }

  lambda_source_directory = abspath(
    "${path.module}/../src/export_pipeline"
  )

  lambda_requirements_file = abspath(
    "${path.module}/../requirements-lambda.txt"
  )

  lambda_build_script = abspath(
    "${path.module}/../scripts/build_lambda_bundle.py"
  )

  lambda_build_directory = abspath(
    "${path.module}/../build/lambda_bundle"
  )

  lambda_archive_path = abspath(
    "${path.module}/../build/lambda_bundle.zip"
  )

  lambda_source_files = fileset(
    "${path.module}/../src/export_pipeline",
    "**/*.py"
  )

  lambda_source_hash = sha256(
    join(
      "",
      concat(
        [
          for file_name in sort(
            tolist(local.lambda_source_files)
          ) :
          filesha256(
            "${path.module}/../src/export_pipeline/${file_name}"
          )
        ],
        [
          filesha256(local.lambda_requirements_file),
          filesha256(local.lambda_build_script)
        ]
      )
    )
  )

  slice_state_machine_name = (
    "${local.name_prefix}-slice"
  )

  parent_state_machine_name = (
    "${local.name_prefix}-parent"
  )

  state_machine_names = {
    slice  = local.slice_state_machine_name
    parent = local.parent_state_machine_name
  }

  lambda_pip_platform = (
    var.lambda_architecture == "arm64"
    ? "manylinux2014_aarch64"
    : "manylinux2014_x86_64"
  )

  lambda_python_version = trimprefix(
    var.lambda_runtime,
    "python"
  )
}