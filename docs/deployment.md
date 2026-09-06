# Deployment Guide

This document describes how to deploy the OpenSearch export pipeline to AWS using Terraform.

## 1. Deployment overview

The deployment process consists of the following steps:

1. Configure AWS credentials.
2. Build the Lambda deployment package.
3. Configure Terraform variables.
4. Initialize Terraform.
5. Validate the infrastructure configuration.
6. Review the Terraform execution plan.
7. Deploy the infrastructure.
8. start and verify an export.
9. Configure production safeguards.

Run Terraform commands from the `terraform` directory unless stated otherwise.

---

## 2. Prerequisites

Install the following tools on the deployment workstation or CI runner:

- Python 3.13
- pip
- Terraform 1.6 or later
- AWS CLI v2
- Git

Verify the installations:

```powershell
py -3.13 --version
terraform version
aws --version
git --version
```

The deployment identity must have permissions to manage:

- AWS Lambda
- AWS Step Functions
- Amazon S3
- Amazon DynamoDB
- AWS IAM
- Amazon CloudWatch
- Amazon VPC security groups and endpoints

For production environments, use a dedicated CI/CD role instead of long-lived IAM user credentials.

---

## 3. Configure AWS authentication

Configure an AWS CLI profile:

```powershell
aws configure --profile opensearch-export
```

Provide:

- AWS access key ID
- AWS secret access key
- Default AWS Region
- Output format

Example Region:

```text
eu-central-1
```

Activate the profile for the current PowerShell session:

```powershell
$env:AWS_PROFILE = "opensearch-export"
```

Verify the current AWS identity:

```powershell
aws sts get-caller-identity
```

Review the returned account ID and ARN before deploying.

Do not deploy if the command points to an unexpected AWS account.

If temporary credentials are used, ensure that the AWS session token is also configured.

---

## 4. Prepare the project

Clone the repository and change to its root directory:

```powershell
git clone <repository-url>
cd opensearch_export_pipeline
```

Create a Python virtual environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install development dependencies:

```powershell
py -3.13 -m pip install --upgrade pip
py -3.13 -m pip install -r requirements.txt
```

Run the automated checks:

```powershell
py -3.13 -m pytest
py -3.13 -m ruff check src tests scripts
```

Do not continue with the deployment if tests or static checks fail.

---

## 5. Build the Lambda deployment package

AWS Lambda functions are configured to use the ARM64 architecture.

Build dependencies for the Linux ARM64 Lambda runtime:

```powershell
py -3.13 scripts/build_lambda_bundle.py `
  --platform manylinux2014_aarch64 `
  --python-version 3.13
```

The build script prepares the artifact used by Terraform to package the Lambda functions.

The package must contain:

- the `export_pipeline` Python package;
- `opensearch-py`;
- runtime dependencies from `requirements-lambda.txt`.

Do not build Lambda dependencies with a regular Windows-only `pip install` command. Packages containing native components must match the Lambda Linux architecture.

After changing application code or runtime dependencies, rebuild the Lambda package before running Terraform.

---

## 6. Configure Terraform variables

Change to the Terraform directory:

```powershell
cd terraform
```

Create the local variables file:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
```

Open `terraform.tfvars` and replace all example values.

The exact variables are documented in `variables.tf` and `terraform.tfvars.example`.

At minimum, review:

- AWS Region;
- environment name;
- OpenSearch domain endpoint;
- VPC ID;
- private subnet IDs;
- security group configuration;
- S3 bucket configuration;
- Lambda timeout and memory settings;
- export page size;
- slice count;
- page-group size;
- Step Functions concurrency;
- log retention;
- DynamoDB job retention.

Do not commit `terraform.tfvars` if it contains environment-specific or sensitive values.

### OpenSearch endpoint format

Provide the complete HTTPS endpoint without an index path or trailing slash.

Example:

```text
https://search-production-example.eu-central-1.es.amazonaws.com
```

The endpoint must:

- start with `https://`;
- not contain an index name;
- not contain query parameters;
- not end with a trailing slash.

### Network configuration

The selected private subnets must have network connectivity to the Amazon OpenSearch Service domain.

Confirm that:

- the subnets belong to the configured VPC;
- route tables and network ACLs permit the required traffic;
- the OpenSearch domain security group accepts HTTPS traffic from the Lambda security group;
- DNS resolution is enabled in the VPC.

Terraform creates or configures the pipeline security group and the required AWS service endpoints according to the project configuration.

---

## 7. Configure the Terraform backend

Production Terraform state should not be stored only on a developer workstation.

Use a remote S3 backend with:

- S3 versioning enabled;
- server-side encryption enabled;
- public access blocked;
- restricted IAM access;
- state locking supported by the selected Terraform/AWS backend configuration.

Backend infrastructure should normally be created separately because Terraform cannot create the backend that it is currently using.

Example backend configuration:

```hcl
terraform {
  backend "s3" {
    bucket       = "company-terraform-state"
    key          = "opensearch-export/production/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

Use a different state key for each environment.

Example:

```text
opensearch-export/development/terraform.tfstate
opensearch-export/staging/terraform.tfstate
opensearch-export/production/terraform.tfstate
```

If the current test assignment does not provide a remote backend, Terraform can use local state temporarily. Local state is not recommended for a shared production environment.

---

## 8. Initialize Terraform

Initialize the working directory:

```powershell
terraform init -upgrade
```

If backend settings have changed, run:

```powershell
terraform init -reconfigure
```

Successful initialization creates or updates the Terraform provider lock file:

```text
.terraform.lock.hcl
```

Commit `.terraform.lock.hcl` to the repository to keep provider versions reproducible.

Do not commit:

```text
.terraform/
terraform.tfstate
terraform.tfstate.backup
terraform.tfvars
```

---

## 9. Format and validate Terraform

Check formatting:

```powershell
terraform fmt -check -recursive
```

If formatting changes are required:

```powershell
terraform fmt -recursive
```

Validate the configuration:

```powershell
terraform validate
```

The expected result is:

```text
Success! The configuration is valid.
```

Resolve all formatting and validation errors before creating a deployment plan.

---

## 10. Create and review the deployment plan

Create a saved Terraform plan:

```powershell
terraform plan -out=tfplan
```

Review the plan carefully.

Confirm that Terraform intends to create or update only the expected resources:

- S3 export bucket;
- DynamoDB jobs table;
- Lambda functions;
- Lambda IAM role and policies;
- Step Functions state machines;
- Step Functions IAM role and policies;
- CloudWatch log groups;
- CloudWatch alarms;
- VPC security group;
- VPC endpoints or endpoint-related resources.

Pay particular attention to actions marked as:

```text
-/+
```

This means Terraform will replace a resource.

Also check for unexpected destroy operations:

```text
- destroy
```

Do not apply a plan containing unexplained replacements or deletions.

The plan file may contain sensitive infrastructure values. Do not commit `tfplan`.

---

## 11. Deploy the infrastructure

Apply the previously reviewed plan:

```powershell
terraform apply tfplan
```

Terraform displays the resources as they are created.

After the deployment completes, inspect the outputs:

```powershell
terraform output
```

Important outputs should include identifiers such as:

- parent Step Functions state machine ARN;
- child slice state machine ARN;
- S3 export bucket name;
- DynamoDB jobs table name;
- Lambda function names;
- CloudWatch log group names.

The exact output names are defined in `outputs.tf`.

---

## 12. Verify the deployed resources

### 12.1 Verify Lambda functions

List the project Lambda functions:

```powershell
aws lambda list-functions `
  --query "Functions[?contains(FunctionName, 'opensearch-export')].[FunctionName,Runtime,Architectures]" `
  --output table
```

Confirm that:

- the expected functions exist;
- the configured Python runtime is correct;
- the architecture is `arm64`;
- functions are attached to the expected VPC and subnets.

### 12.2 Verify Step Functions

List the state machines:

```powershell
aws stepfunctions list-state-machines --output table
```

Confirm that both the parent and slice state machines exist.

### 12.3 Verify the S3 bucket

Use the bucket name returned by Terraform:

```powershell
aws s3api get-bucket-encryption --bucket <export-bucket-name>
aws s3api get-public-access-block --bucket <export-bucket-name>
```

Confirm that encryption is enabled and public access is blocked.

### 12.4 Verify the DynamoDB table

```powershell
aws dynamodb describe-table `
  --table-name <jobs-table-name> `
  --query "Table.[TableName,TableStatus,BillingModeSummary.BillingMode]" `
  --output table
```

The table status must be:

```text
ACTIVE
```

### 12.5 Verify CloudWatch alarms

```powershell
aws cloudwatch describe-alarms `
  --alarm-name-prefix <project-name> `
  --output table
```

New alarms may initially have the `INSUFFICIENT_DATA` state. This is expected until metrics are available.

---

## 13. Start a verification export

Obtain the parent state machine ARN:

```powershell
terraform output
```

If `outputs.tf` defines `parent_state_machine_arn`, it can be read directly:

```powershell
$STATE_MACHINE_ARN = terraform output -raw parent_state_machine_arn
```

Create a file named `export-input.json` in the repository root:

```json
{
  "requestId": "deployment-verification-001",
  "index": "example-index",
  "query": {
    "match_all": {}
  },
  "pageSize": 1000,
  "sliceCount": 4
}
```

Start the export:

```powershell
aws stepfunctions start-execution `
  --state-machine-arn $STATE_MACHINE_ARN `
  --name "deployment-verification-001" `
  --input file://../export-input.json
```

Step Functions execution names must be unique for the retention period enforced by AWS Step Functions.

For repeated tests, use a unique name:

```powershell
$EXECUTION_NAME = "deployment-verification-" + (Get-Date -Format "yyyyMMdd-HHmmss")
```

Then start the execution:

```powershell
aws stepfunctions start-execution `
  --state-machine-arn $STATE_MACHINE_ARN `
  --name $EXECUTION_NAME `
  --input file://../export-input.json
```

The `requestId` should also be unique unless idempotent replay behavior is being tested.

---

## 14. Monitor the verification export

Open the parent workflow in the AWS Step Functions console or retrieve its execution history with the AWS CLI.

Check recent executions:

```powershell
aws stepfunctions list-executions `
  --state-machine-arn $STATE_MACHINE_ARN `
  --max-results 10 `
  --output table
```

When the workflow completes, verify that:

- the parent execution status is `SUCCEEDED`;
- all slice executions completed;
- the DynamoDB job status is `COMPLETED`;
- page files exist in S3;
- the manifest file exists in S3;
- the OpenSearch PIT was closed;
- no Lambda or Step Functions error alarms are active.

List the exported objects:

```powershell
aws s3 ls s3://<export-bucket-name>/exports/ --recursive
```

Download and inspect the manifest:

```powershell
aws s3 cp `
  s3://<export-bucket-name>/exports/<request-id>/manifest.json `
  .\manifest.json
```

The exact key prefix is determined by the application configuration and manifest implementation.

---

## 15. Deploy application updates

For Python application changes:

1. Run tests and Ruff.
2. Rebuild the Lambda bundle.
3. Create a new Terraform plan.
4. Review the plan.
5. Apply the plan.
6. Run a verification export.

Example:

```powershell
cd C:\EPAM\GitHub\opensearch_export_pipeline

py -3.13 -m pytest
py -3.13 -m ruff check src tests scripts

py -3.13 scripts/build_lambda_bundle.py `
  --platform manylinux2014_aarch64 `
  --python-version 3.13

cd terraform

terraform fmt -check -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

Terraform detects changes to the generated Lambda archive and updates the affected functions.

For Step Functions definition changes, Terraform updates the state machine definitions during `terraform apply`.

---

## 16. Production deployment recommendations

Before deploying to production, implement the following controls:

- use a dedicated AWS account or clearly separated production environment;
- deploy through CI/CD using temporary credentials;
- require review and approval of the Terraform plan;
- store Terraform state remotely;
- enable S3 state versioning and encryption;
- restrict access to the Terraform state;
- use separate state files for development, staging, and production;
- test changes in staging before production;
- configure CloudWatch alarm notifications through Amazon SNS;
- define log and S3 lifecycle retention policies;
- set Step Functions concurrency according to OpenSearch capacity;
- test OpenSearch throttling and Lambda retry behavior;
- document recovery and incident-response procedures;
- tag all AWS resources for ownership and cost allocation.

Do not use production as the first environment in which a new Lambda package or state machine definition is tested.

---

## 17. Rollback strategy

Terraform does not automatically provide application-level rollback.

Before production deployment:

1. Record the currently deployed Git commit.
2. Save the reviewed Terraform plan.
3. Confirm that the previous Lambda artifact can be rebuilt.
4. Ensure Terraform state versioning is enabled.
5. Verify that S3 export data is protected by the required retention policy.

To roll back application code:

1. Check out the previously known-good Git commit.
2. Rebuild the Lambda package.
3. Run `terraform plan`.
4. Review all proposed changes.
5. Run `terraform apply`.

Example:

```powershell
git checkout <known-good-commit>

py -3.13 scripts/build_lambda_bundle.py `
  --platform manylinux2014_aarch64 `
  --python-version 3.13

cd terraform
terraform plan -out=rollback.tfplan
terraform apply rollback.tfplan
```

Do not manually replace Terraform-managed Lambda code in the AWS console. Manual changes create configuration drift.

A rollback does not automatically undo:

- already completed exports;
- S3 objects;
- DynamoDB job records;
- data changes in OpenSearch.

---

## 18. Removing an environment

Destruction is a high-risk operation and should not be part of the normal deployment workflow.

First, create and review a destroy plan:

```powershell
terraform plan -destroy -out=destroy.tfplan
```

Review every resource scheduled for deletion.

If the S3 bucket contains exported objects, Terraform may be unable to delete it unless force deletion is explicitly configured. Production buckets should normally protect data from accidental deletion.

Only after explicit approval, apply the destroy plan:

```powershell
terraform apply destroy.tfplan
```

Before destroying an environment:

- stop new workflow executions;
- wait for running exports to complete or stop them safely;
- preserve required manifests and exported data;
- back up required DynamoDB records;
- confirm that the correct AWS account and environment are selected;
- confirm that Terraform is using the correct state file.

Never run `terraform destroy` against an unidentified workspace or AWS account.

---

## 19. Common deployment problems

### Terraform command is not found

Terraform is either not installed or is not available through `PATH`.

Verify:

```powershell
terraform version
```

Restart PowerShell after changing `PATH`.

### AWS credentials are unavailable

Verify:

```powershell
aws sts get-caller-identity
```

Check `AWS_PROFILE` and refresh temporary credentials if required.

### Lambda cannot import a dependency

Rebuild the package for Linux ARM64:

```powershell
py -3.13 scripts/build_lambda_bundle.py `
  --platform manylinux2014_aarch64 `
  --python-version 3.13
```

Do not reuse dependencies installed for Windows.

### Lambda cannot connect to OpenSearch

Check:

- VPC ID;
- private subnet IDs;
- Lambda security group;
- OpenSearch security group inbound rules;
- network ACLs;
- DNS settings;
- OpenSearch endpoint;
- IAM domain access policy.

### Lambda cannot access S3 or DynamoDB

Check:

- Lambda IAM permissions;
- S3 and DynamoDB VPC endpoints;
- endpoint policies;
- resource policies;
- AWS Region configuration.

### Step Functions cannot invoke Lambda

Check:

- Step Functions execution role;
- Lambda ARNs referenced by the state machine;
- IAM `lambda:InvokeFunction` permissions;
- Terraform state machine substitutions.

### Terraform reports configuration drift

Run:

```powershell
terraform plan
```

Investigate changes made outside Terraform.

Import or reconcile legitimate external changes. Do not apply the plan blindly if it proposes unexpected replacements or deletions.

---

## 20. Deployment completion checklist

A deployment is complete only when all of the following are confirmed:

- Python tests pass.
- Ruff checks pass.
- Terraform formatting passes.
- Terraform validation passes.
- Terraform plan was reviewed.
- Terraform apply completed successfully.
- Lambda functions use the expected runtime and architecture.
- Lambda functions have OpenSearch network connectivity.
- Parent and slice state machines exist.
- S3 encryption and public-access blocking are enabled.
- DynamoDB table is active.
- CloudWatch log groups and alarms exist.
- A verification export completed successfully.
- Exported page objects exist in S3.
- The manifest exists and contains expected totals.
- The DynamoDB job has `COMPLETED` status.
- No unexpected secrets or state files were committed.