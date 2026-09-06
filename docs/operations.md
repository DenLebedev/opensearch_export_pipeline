# Operations Guide

This document describes how to operate, monitor, troubleshoot, and maintain the OpenSearch export pipeline after deployment.

## 1. Operational responsibilities

The team operating the pipeline is responsible for:

- monitoring Step Functions executions;
- monitoring Lambda errors, duration, and throttling;
- monitoring OpenSearch capacity and throttling;
- monitoring failed or incomplete export jobs;
- verifying that exported files and manifests are written to S3;
- responding to CloudWatch alarms;
- controlling export concurrency;
- managing data retention;
- reviewing AWS cost and resource usage;
- safely deploying and rolling back changes.

The pipeline is asynchronous. Starting an export only creates a Step Functions execution. The caller must check the execution or job status separately.

---

## 2. Export lifecycle

A normal export passes through the following logical states:

| Status | Meaning |
|---|---|
| `RUNNING` | The export was initialized and is currently being processed |
| `COMPLETED` | All slices completed and the manifest was created |
| `FAILED` | The workflow failed, if failure status persistence is implemented |
| Expired record | DynamoDB TTL removed an old job record |

The exact status fields are defined in:

```text
src/export_pipeline/common/models.py
src/export_pipeline/common/job_store.py
```

The Step Functions execution status is the primary source for workflow execution state.

Possible Step Functions execution statuses include:

- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `TIMED_OUT`
- `ABORTED`

A `SUCCEEDED` workflow should have a corresponding completed job and manifest in S3.

---

## 3. Starting an export

Use the parent Step Functions state machine to start an export.

Example input:

```json
{
  "requestId": "customer-export-20260906-001",
  "index": "customer-index",
  "query": {
    "bool": {
      "filter": [
        {
          "term": {
            "status.keyword": "active"
          }
        }
      ]
    }
  },
  "pageSize": 1000,
  "sliceCount": 16
}
```

Save the request as `export-input.json`.

Get the parent state machine ARN:

```powershell
cd terraform
$STATE_MACHINE_ARN = terraform output -raw parent_state_machine_arn
```

Create a unique Step Functions execution name:

```powershell
$EXECUTION_NAME = "export-" + (Get-Date -Format "yyyyMMdd-HHmmss")
```

Start the execution:

```powershell
aws stepfunctions start-execution `
  --state-machine-arn $STATE_MACHINE_ARN `
  --name $EXECUTION_NAME `
  --input file://../export-input.json
```

The command returns an execution ARN. Save it because it is the easiest way to monitor the export.

Example:

```json
{
  "executionArn": "arn:aws:states:eu-central-1:123456789012:execution:opensearch-export-parent:export-20260906-120000",
  "startDate": "2026-09-06T12:00:00+00:00"
}
```

---

## 4. Request ID rules

The `requestId` identifies the logical export job.

Use a value that is:

- unique for a new export;
- safe for use in DynamoDB and S3 keys;
- traceable to the originating system;
- free of confidential information.

Recommended format:

```text
<source>-<purpose>-<timestamp-or-business-id>
```

Example:

```text
crm-active-customers-20260906-001
```

Do not include:

- passwords;
- access tokens;
- personal data;
- complete OpenSearch queries;
- spaces or control characters.

A repeated `requestId` is treated as an idempotency request. It must not be used when a completely new export is required.

---

## 5. Checking an execution

Describe a specific execution:

```powershell
$EXECUTION_ARN = "<execution-arn>"

aws stepfunctions describe-execution `
  --execution-arn $EXECUTION_ARN
```

Return only the most important fields:

```powershell
aws stepfunctions describe-execution `
  --execution-arn $EXECUTION_ARN `
  --query "{status:status,startDate:startDate,stopDate:stopDate,error:error,cause:cause}" `
  --output json
```

List recent executions:

```powershell
aws stepfunctions list-executions `
  --state-machine-arn $STATE_MACHINE_ARN `
  --max-results 20 `
  --output table
```

List only failed executions:

```powershell
aws stepfunctions list-executions `
  --state-machine-arn $STATE_MACHINE_ARN `
  --status-filter FAILED `
  --max-results 20 `
  --output table
```

---

## 6. Inspecting execution history

Retrieve the execution history:

```powershell
aws stepfunctions get-execution-history `
  --execution-arn $EXECUTION_ARN `
  --reverse-order `
  --max-results 100
```

When investigating a failure, look for events such as:

- `LambdaFunctionFailed`
- `LambdaFunctionTimedOut`
- `TaskFailed`
- `MapRunFailed`
- `ExecutionFailed`
- `ExecutionTimedOut`
- `ExecutionAborted`

The failure event normally contains:

- the failed state name;
- an AWS error code;
- an error message;
- the Lambda request ID;
- a nested child execution ARN.

For a distributed map, inspect both:

1. the parent workflow;
2. the failed child slice workflow.

A successful parent execution means that all required slice workflows completed successfully.

---

## 7. Monitoring child slice workflows

The parent state machine starts one child execution for each OpenSearch slice.

List executions of the slice state machine:

```powershell
$SLICE_STATE_MACHINE_ARN = terraform output -raw slice_state_machine_arn

aws stepfunctions list-executions `
  --state-machine-arn $SLICE_STATE_MACHINE_ARN `
  --max-results 50 `
  --output table
```

If one slice fails, identify:

- the slice ID;
- the parent request ID;
- the last successful page;
- the current `search_after` value;
- the Lambda error that caused the failure.

Do not assume that every slice processes the same number of documents. OpenSearch slicing distributes work, but slice sizes may differ.

---

## 8. Checking the DynamoDB job record

Get the table name from Terraform:

```powershell
$JOBS_TABLE = terraform output -raw export_jobs_table_name
```

Create a temporary file named `job-key.json`:

```json
{
  "requestId": {
    "S": "customer-export-20260906-001"
  }
}
```

Read the job:

```powershell
aws dynamodb get-item `
  --table-name $JOBS_TABLE `
  --key file://../job-key.json `
  --consistent-read
```

The record may contain fields such as:

- `requestId`;
- `executionId`;
- `status`;
- `pitId`;
- `index`;
- `queryHash`;
- `createdAt`;
- `updatedAt`;
- `expiresAt`;
- manifest information;
- exported document totals.

Do not manually change a running job record unless the recovery procedure has been reviewed and approved.

DynamoDB TTL deletion is asynchronous. An expired record may remain visible for some time after its expiration timestamp.

---

## 9. Checking exported files in S3

Get the bucket name:

```powershell
$EXPORT_BUCKET = terraform output -raw export_bucket_name
```

List objects for a request:

```powershell
aws s3 ls `
  "s3://$EXPORT_BUCKET/exports/customer-export-20260906-001/" `
  --recursive
```

A successful export should contain:

- one or more compressed page files;
- files grouped by slice;
- a final manifest.

Example logical structure:

```text
exports/
└── customer-export-20260906-001/
    ├── slices/
    │   ├── slice-00000/
    │   │   ├── page-00000000.jsonl.gz
    │   │   └── page-00000001.jsonl.gz
    │   └── slice-00001/
    │       └── page-00000000.jsonl.gz
    └── manifest.json
```

The exact key structure is defined in:

```text
src/export_pipeline/common/s3_client.py
src/export_pipeline/export_page_group/handler.py
src/export_pipeline/finalize_export/handler.py
```

Download the manifest:

```powershell
aws s3 cp `
  "s3://$EXPORT_BUCKET/exports/customer-export-20260906-001/manifest.json" `
  .\manifest.json
```

Inspect it:

```powershell
Get-Content .\manifest.json
```

---

## 10. Verifying exported page files

Exported page files use compressed JSON Lines format:

```text
.jsonl.gz
```

Each line represents one OpenSearch document.

Download one page:

```powershell
aws s3 cp `
  "s3://$EXPORT_BUCKET/<page-object-key>" `
  .\page.jsonl.gz
```

Extract it with Python:

```powershell
py -3.13 -c "import gzip; print(gzip.open('page.jsonl.gz', 'rt', encoding='utf-8').read())"
```

For a large page, inspect only the first few records:

```powershell
py -3.13 -c "import gzip, itertools; f=gzip.open('page.jsonl.gz','rt',encoding='utf-8'); print(''.join(itertools.islice(f,5)))"
```

Validate that:

- every line is valid JSON;
- document identifiers are present where expected;
- the `_source` content matches the export requirements;
- the file is not empty unless the corresponding slice had no results.

Do not print production documents containing sensitive data into CI logs or shared terminals.

---

## 11. Manifest verification

The manifest represents the final result of the export.

Verify that it contains the expected information:

- request ID;
- source index;
- creation or completion timestamp;
- slice count;
- page count;
- exported document count;
- S3 location information;
- final export status.

Check the following consistency rules:

1. The manifest exists only after successful finalization.
2. The sum of slice document counts equals the manifest document count.
3. The reported page count matches the page objects in S3.
4. Every referenced S3 object exists.
5. The DynamoDB job status is `COMPLETED`.
6. The parent Step Functions execution status is `SUCCEEDED`.

A missing manifest means the export must not be treated as complete, even when some page files exist.

---

## 12. CloudWatch Lambda logs

Each Lambda function writes logs to CloudWatch Logs.

Important functions include:

- initialize export;
- export page group;
- cleanup export;
- finalize export.

Use Terraform outputs or the AWS console to locate the exact log group names.

Typical Lambda log group format:

```text
/aws/lambda/<function-name>
```

Follow recent logs:

```powershell
aws logs tail "/aws/lambda/<function-name>" `
  --since 30m `
  --follow
```

Show recent errors:

```powershell
aws logs filter-log-events `
  --log-group-name "/aws/lambda/<function-name>" `
  --start-time <unix-time-in-milliseconds> `
  --filter-pattern "ERROR"
```

Useful correlation identifiers include:

- `requestId`;
- Step Functions execution ID;
- Lambda request ID;
- slice ID;
- page number;
- S3 object key.

Do not log:

- AWS credentials;
- authorization headers;
- complete PIT IDs;
- confidential document contents;
- complete queries containing personal information.

---

## 13. Key CloudWatch metrics

### Lambda metrics

Monitor:

| Metric | Meaning |
|---|---|
| `Errors` | Lambda invocations that failed |
| `Duration` | Function execution time |
| `Throttles` | Invocations rejected because concurrency was unavailable |
| `ConcurrentExecutions` | Current Lambda concurrency |
| `Invocations` | Number of function calls |
| `IteratorAge` | Not applicable unless an event stream is later introduced |

The page export Lambda is the main performance-sensitive function.

Its duration should remain safely below the configured Lambda timeout.

### Step Functions metrics

Monitor:

| Metric | Meaning |
|---|---|
| `ExecutionsFailed` | Failed workflow executions |
| `ExecutionsTimedOut` | Workflows that exceeded their timeout |
| `ExecutionsAborted` | Manually stopped executions |
| `ExecutionsSucceeded` | Successfully completed workflows |
| `ExecutionTime` | Total workflow duration |

### OpenSearch metrics

Monitor at least:

| Metric | Operational concern |
|---|---|
| `ClusterStatus.red` | Data or cluster availability problem |
| `ClusterStatus.yellow` | Replica allocation or capacity problem |
| `CPUUtilization` | Sustained compute pressure |
| `JVMMemoryPressure` | JVM memory pressure |
| `FreeStorageSpace` | Risk of unavailable writes or degraded cluster |
| `ThreadpoolSearchRejected` | Search requests rejected |
| `SearchLatency` | Increased query response time |
| `MasterReachableFromNode` | Cluster coordination problem |

Export concurrency must be reduced when OpenSearch is under sustained pressure.

### DynamoDB metrics

Monitor:

- `SystemErrors`;
- `UserErrors`;
- `ThrottledRequests`;
- `ConsumedReadCapacityUnits`;
- `ConsumedWriteCapacityUnits`.

For on-demand billing, occasional workload variation does not require manual capacity configuration, but throttling and account limits must still be monitored.

### S3 metrics

Monitor:

- failed requests;
- `4xxErrors`;
- `5xxErrors`;
- storage growth;
- lifecycle transitions;
- incomplete multipart uploads, if multipart upload is introduced.

---

## 14. Alarm response procedure

When a CloudWatch alarm enters the `ALARM` state:

1. Identify the affected resource.
2. Record the alarm name and timestamp.
3. Find related Step Functions executions.
4. Find related Lambda log events.
5. Determine whether OpenSearch was unhealthy or throttling requests.
6. Determine whether the failure is temporary or persistent.
7. Avoid starting additional large exports until impact is understood.
8. Apply the appropriate recovery procedure.
9. Confirm that the alarm returns to `OK`.
10. Document the cause and corrective action.

Do not immediately increase retries or concurrency. This can amplify an OpenSearch capacity incident.

---

## 15. Common failure scenarios

### 15.1 OpenSearch throttling

Typical symptoms:

- HTTP `429` responses;
- search thread-pool rejections;
- increasing search latency;
- Lambda retries;
- failed slice executions.

Actions:

1. Pause new export requests.
2. Check OpenSearch CPU, JVM pressure, and search rejection metrics.
3. Reduce Step Functions map concurrency.
4. Reduce the slice count for new exports.
5. Consider reducing the page size.
6. Wait for the cluster to recover.
7. Start a new export with a new `requestId`.

Repeated aggressive retries can make throttling worse.

### 15.2 OpenSearch connection timeout

Typical causes:

- incorrect endpoint;
- security group rules;
- subnet routing;
- DNS failure;
- overloaded OpenSearch domain;
- timeout configured too low.

Actions:

1. Check the Lambda VPC configuration.
2. Check Lambda and OpenSearch security groups.
3. Check the OpenSearch domain status.
4. Verify DNS support in the VPC.
5. Review the Lambda timeout and OpenSearch client timeout.
6. Review CloudWatch logs for the exact connection error.

### 15.3 Access denied by OpenSearch

Typical symptoms:

- HTTP `401`;
- HTTP `403`;
- authorization errors in Lambda logs.

Actions:

1. Verify the Lambda execution role.
2. Verify the OpenSearch domain access policy.
3. Verify fine-grained access control role mappings, if enabled.
4. Confirm that the role can read the requested index.
5. Confirm permissions for PIT and search operations.

### 15.4 Lambda timeout

Typical symptoms:

- `Task timed out`;
- duration close to the configured timeout;
- a page group stops before returning its state.

Actions:

1. Check OpenSearch search latency.
2. Check the page size.
3. Check the number of pages processed per Lambda invocation.
4. Check remaining-time protection in the page worker.
5. Increase timeout only after identifying the cause.
6. Reduce page-group size if individual invocations are too long.

The handler should stop before the hard Lambda timeout when insufficient execution time remains.

### 15.5 Lambda throttling

Typical symptoms:

- Lambda `Throttles` metric increases;
- Step Functions receives invocation throttling errors;
- workflows take longer than expected.

Actions:

1. Check account concurrency limits.
2. Check function reserved concurrency.
3. Reduce distributed-map concurrency.
4. Check whether other workloads share the same account concurrency pool.
5. Request a quota increase only when sustained capacity is justified.

### 15.6 S3 access failure

Typical symptoms:

- `AccessDenied`;
- failure to upload page files;
- missing manifest;
- endpoint connectivity errors.

Actions:

1. Verify Lambda IAM permissions.
2. Verify the bucket policy.
3. Verify the S3 VPC endpoint and endpoint policy.
4. Verify the bucket Region.
5. Verify KMS permissions if customer-managed KMS keys are used.
6. Check whether the bucket name or prefix is incorrect.

### 15.7 DynamoDB access failure

Typical symptoms:

- `AccessDeniedException`;
- `ResourceNotFoundException`;
- throttled requests;
- failed initialization or finalization.

Actions:

1. Verify the table name in Lambda environment variables.
2. Verify the Lambda IAM role.
3. Verify the DynamoDB VPC endpoint.
4. Verify the endpoint policy.
5. Confirm that the table is `ACTIVE`.
6. Check that the partition key matches the application model.

### 15.8 Step Functions cannot invoke Lambda

Typical symptoms:

- `Lambda.AWSLambdaException`;
- `Lambda.ServiceException`;
- `AccessDeniedException`.

Actions:

1. Verify the state machine execution role.
2. Verify `lambda:InvokeFunction` permissions.
3. Verify the Lambda ARN in the state machine definition.
4. Run `terraform plan` to detect configuration drift.
5. Check whether the Lambda function was renamed or replaced.

### 15.9 Missing manifest

Possible causes:

- one or more slices failed;
- finalize Lambda failed;
- S3 write failed;
- DynamoDB update failed;
- workflow was manually stopped.

Actions:

1. Check the parent execution status.
2. Inspect failed slice executions.
3. Inspect finalize Lambda logs.
4. Check whether all expected page objects exist.
5. Check the DynamoDB job status.
6. Do not mark or report the export as complete manually.

---

## 16. Retry and restart policy

The pipeline already uses controlled retries for temporary service failures.

Operators should not start repeated manual retries while an execution is still running.

### Same execution retry

Retries performed inside the same Step Functions execution use the same execution identity.

The initialization logic can recognize the current workflow execution and avoid creating a duplicate job.

### New export attempt

Use a new `requestId` when:

- a previous execution permanently failed;
- its PIT was closed or expired;
- the workflow was aborted;
- the export query changed;
- a new independent output is required.

Example:

```text
customer-export-20260906-001
customer-export-20260906-002
```

### Step Functions redrive

Before using Step Functions redrive, verify:

- which state will be resumed;
- whether the OpenSearch PIT still exists;
- whether cleanup already closed the PIT;
- whether page files already exist;
- whether the workflow preserves the required slice state.

Do not redrive an execution when its PIT is known to be closed or expired.

In that case, start a new execution with a new `requestId`.

---

## 17. Idempotency and duplicate files

Page files use deterministic S3 keys.

Retrying the same page should write to the same key rather than create an additional object.

This provides idempotent object creation, but it also means that a retry can replace an existing object with the same key.

When investigating retry behavior:

1. Compare the S3 key.
2. Check the object `LastModified` timestamp.
3. Check the object size.
4. Check version history if S3 versioning is enabled.
5. Check Lambda logs for repeated page processing.

Do not manually combine files from different `requestId` values into one export.

---

## 18. Stopping a running export

Stopping an execution is an exceptional operation.

Stop the parent execution:

```powershell
aws stepfunctions stop-execution `
  --execution-arn $EXECUTION_ARN `
  --error "OperatorAbort" `
  --cause "Stopped by operator because <reason>"
```

After stopping it:

1. Confirm that the parent status is `ABORTED`.
2. Check whether child slice executions are still running.
3. Stop remaining child executions if necessary.
4. Check whether the cleanup Lambda ran.
5. Check whether the PIT was closed.
6. Record the affected request ID.
7. Decide whether partial S3 files must be retained or removed.
8. Use a new request ID for a replacement export.

A direct `stop-execution` operation may prevent normal workflow cleanup states from running.

OpenSearch PITs eventually expire according to their keep-alive setting, but operators should not rely on expiration as the normal cleanup mechanism.

---

## 19. Partial export data

A failed or aborted export may leave page files in S3.

These files are incomplete and must not be consumed as a completed export.

The manifest is the completion marker:

- page files without a manifest represent an incomplete export;
- a valid manifest represents a completed export.

Before deleting partial data:

1. Verify the request ID.
2. Verify that no execution for the request is running.
3. Record the failure or incident reference.
4. Confirm that the data is not required for investigation.
5. Review the exact S3 prefix.

Preview the objects:

```powershell
aws s3 ls `
  "s3://$EXPORT_BUCKET/exports/<request-id>/" `
  --recursive
```

Only after verifying the exact prefix, remove the incomplete export:

```powershell
aws s3 rm `
  "s3://$EXPORT_BUCKET/exports/<request-id>/" `
  --recursive
```

This operation is destructive.

If S3 versioning is enabled, delete markers may be recoverable. If versioning is not enabled, deleted objects may not be recoverable.

---

## 20. PIT lifecycle

A Point in Time provides a stable view of the OpenSearch index during pagination.

The PIT is created during initialization and should be closed during cleanup.

A PIT can become unavailable because:

- its keep-alive period expired;
- cleanup closed it;
- the OpenSearch cluster restarted or became unavailable;
- the workflow was delayed longer than expected.

Typical PIT-related errors include:

- PIT not found;
- search context missing;
- resource not found;
- invalid PIT ID.

A closed or expired PIT cannot be safely recreated in the middle of the same export because the new PIT may represent a different index state.

Start a new export with a new request ID instead.

---

## 21. Concurrency tuning

Export concurrency affects both performance and OpenSearch load.

The main controls are:

- slice count;
- distributed-map maximum concurrency;
- Lambda reserved concurrency;
- page size;
- number of pages processed by one Lambda invocation.

### Increasing concurrency

Potential benefits:

- shorter export duration;
- better use of a sufficiently large OpenSearch cluster.

Potential risks:

- OpenSearch throttling;
- higher CPU and JVM pressure;
- more Lambda concurrency;
- higher Step Functions transition rate;
- increased cost.

### Reducing concurrency

Potential benefits:

- lower OpenSearch load;
- fewer rejected searches;
- more predictable production impact.

Potential costs:

- longer export duration;
- longer PIT lifetime;
- slower delivery of results.

Change concurrency gradually and measure the result.

Recommended tuning process:

1. Record the current configuration.
2. Run a representative export.
3. Measure total duration.
4. Measure OpenSearch CPU and JVM pressure.
5. Measure search latency and rejections.
6. Change only one main parameter.
7. Repeat the export.
8. Compare results.
9. Keep the lowest-cost configuration that satisfies the required completion time.

Do not use the maximum possible concurrency by default.

---

## 22. Page-size tuning

A larger page size reduces the number of OpenSearch requests and Step Functions iterations.

However, it also increases:

- Lambda memory usage;
- response size;
- gzip processing time;
- S3 object size;
- OpenSearch work per search request.

A smaller page size reduces memory pressure but increases:

- request count;
- Lambda invocations;
- Step Functions state transitions;
- total coordination overhead.

Start with the configured default and tune using representative documents.

Documents with large `_source` payloads may require a smaller page size.

---

## 23. Cost monitoring

The main cost sources are:

- Step Functions state transitions and distributed map processing;
- Lambda duration and invocations;
- S3 storage and requests;
- DynamoDB reads and writes;
- CloudWatch logs and metrics;
- OpenSearch compute and storage;
- optional NAT Gateway traffic;
- optional KMS requests.

Cost-control recommendations:

- use VPC endpoints for S3 and DynamoDB;
- avoid routing AWS service traffic through a NAT Gateway;
- use ARM64 Lambda where supported;
- avoid excessive Step Functions iterations;
- process a bounded group of pages per Lambda invocation;
- compress export files;
- configure CloudWatch log retention;
- configure S3 lifecycle policies;
- use DynamoDB on-demand billing for irregular workloads;
- keep concurrency within actual performance requirements;
- avoid logging complete documents.

Review cost after representative staging and production exports.

---

## 24. Routine operational checks

### Daily

- Check active CloudWatch alarms.
- Check failed parent executions.
- Check Lambda errors and throttles.
- Check OpenSearch cluster health.
- Check whether unusually long exports are still running.

### Weekly

- Review incomplete or abandoned export jobs.
- Review S3 storage growth.
- Review Lambda duration trends.
- Review OpenSearch search latency and rejections.
- Review AWS cost by service and resource tags.

### Monthly

- Review log retention settings.
- Review S3 lifecycle behavior.
- Review IAM permissions.
- Review Terraform drift.
- Review dependency and runtime support status.
- Review service quotas.
- Test the operational recovery procedure in a non-production environment.

---

## 25. Terraform drift check

Run a regular Terraform plan without applying it:

```powershell
cd terraform
terraform init
terraform plan
```

A no-change result should report:

```text
No changes. Your infrastructure matches the configuration.
```

Investigate unexpected changes before applying them.

Do not use Terraform to overwrite legitimate emergency changes until the incident and required final configuration are understood.

---

## 26. Security operations

Regularly verify:

- S3 public access remains blocked;
- S3 encryption remains enabled;
- DynamoDB encryption remains enabled;
- Step Functions logging does not expose sensitive input;
- Lambda logs do not contain exported documents;
- IAM permissions follow least privilege;
- the OpenSearch domain is not publicly exposed;
- security groups allow only required traffic;
- AWS credentials are not stored in source control;
- Terraform state access is restricted.

If credentials or secrets appear in logs:

1. Treat them as compromised.
2. Revoke or rotate them immediately.
3. Restrict access to the affected log group.
4. Remove or redact data according to the organization’s incident process.
5. fix application logging.
6. document the incident.

---

## 27. Incident response checklist

For a production incident:

1. Record the time and affected environment.
2. Record the request IDs and execution ARNs.
3. Pause new large exports if they may increase impact.
4. Check Step Functions execution state.
5. Check Lambda errors and throttles.
6. Check OpenSearch health and capacity.
7. Check S3 and DynamoDB availability.
8. Determine whether the issue is application, infrastructure, permissions, networking, or capacity related.
9. Preserve relevant logs and execution history.
10. Apply the smallest safe corrective action.
11. Verify recovery with a controlled export.
12. Monitor the system after recovery.
13. Document the root cause and preventive action.

Avoid changing several concurrency, timeout, and retry parameters at the same time. Multiple simultaneous changes make the result difficult to evaluate.

---

## 28. Post-incident review

A post-incident review should document:

- what happened;
- customer or business impact;
- affected exports;
- start and end times;
- detection method;
- technical root cause;
- contributing conditions;
- recovery actions;
- whether data was incomplete or duplicated;
- whether PIT cleanup completed;
- monitoring gaps;
- corrective actions and owners.

The review should focus on system and process improvements rather than individual blame.

---

## 29. Operational completion criteria

An export can be reported as successfully completed only when:

- the parent Step Functions execution is `SUCCEEDED`;
- all required slice workflows succeeded;
- the DynamoDB job is `COMPLETED`;
- the manifest exists;
- manifest totals are internally consistent;
- referenced S3 page files exist;
- no unresolved error occurred during finalization;
- the PIT cleanup step completed or closure was otherwise verified.

If any of these conditions is missing, treat the export as incomplete until investigated.