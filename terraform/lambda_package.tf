resource "terraform_data" "lambda_build" {
  input = local.lambda_source_hash

  provisioner "local-exec" {
    command = join(
      " ",
      [
        var.python_command,
        "\"${local.lambda_build_script}\"",
        "--source",
        "\"${local.lambda_source_directory}\"",
        "--requirements",
        "\"${local.lambda_requirements_file}\"",
        "--output",
        "\"${local.lambda_build_directory}\""
      ]
    )
  }
}

data "archive_file" "lambda_bundle" {
  type        = "zip"
  source_dir  = local.lambda_build_directory
  output_path = local.lambda_archive_path

  depends_on = [
    terraform_data.lambda_build
  ]
}