# Customer API Lambda diagnostics

`INIT_START` identifies runtime initialization. It does not confirm that the handler
ran or that the database was reached. The API's 503 after about 29 seconds suggests
an integration timeout; it does not identify the underlying dependency.

## Deploy the diagnostic changes

From the repository root:

```bash
git pull --ff-only
sam build --use-container --template infrastructure/template.yaml
sam deploy
```

Use the existing backend stack and its saved parameters. Verify that database secret
and KMS parameters contain real ARNs, not `y`. Docker must be running for the
container build. This update does not require rebuilding the frontend. To also deploy the Cognito
token-generation diagnostics, run `bash scripts/frontend/deploy-auth.sh` with the
existing auth stack configuration.

## Read the correct log group

Open the Customer Management nested stack, locate the **CustomerFunction** physical
Lambda resource, then choose Monitor > View CloudWatch logs. Use all recent log
streams (not only an older initialization stream). This is not OutboxPublisher.

Alternatively, replace the placeholder with that physical function name:

```bash
aws logs tail '/aws/lambda/<CustomerFunction-physical-name>' \
  --region ap-south-1 --since 15m --follow
```

Retry the customer request once while watching the logs. Diagnostic JSON records
include `stage`, `status`, elapsed milliseconds on completion/failure, Lambda
`requestId` and API Gateway `gatewayRequestId` during requests. The latter matches
the API access-log request ID. Customer-operation logs also include `correlationId`.

| Last started or failed stage | What to investigate |
| --- | --- |
| No `module_import` after `INIT_START` | Confirm the new code/version and correct function/log stream; inspect `INIT_REPORT`, runtime import errors, attached layers/extensions and application log filtering. The application may not yet have started. |
| `module_import` without completion | Dependency imports, deployment package, runtime/layer compatibility. |
| `identity_validation` | Verified API Gateway claims and Cognito trigger configuration. |
| `aws_sdk_import` or `secrets_client` | SDK initialization, region and execution-role credential availability. |
| `secret_fetch` | Secrets Manager HTTPS reachability through NAT or a VPC endpoint; endpoint security groups/private DNS, secret permissions and KMS decrypt permissions. |
| `secret_decode` | Secret must be valid JSON containing `username` and `password`. |
| `database_connect` | DB/proxy endpoint, DNS, TCP 5432 security groups, database credentials/name and the CA bundle layer at `/opt/certs/global-bundle.pem`. |
| `database_query` | SQLSTATE, migration completion, database privileges, locks and statement timeout. SQL and query parameters are deliberately omitted. |
| `database_transaction` | An inner phase failure or commit/rollback error. Check the earlier failure record first. |

A phase with `started` and no completion/failure before Lambda's timeout identifies
where execution was interrupted. A failed phase records exception type and SQLSTATE,
without exception messages, secret values, SQL, tokens or request bodies. Nested
phases can each report the same exception; the earliest failed phase is most useful.
A completed invocation can still have a handled HTTP error; check `response.statusCode`.

Secrets Manager now uses 3-second connect/read timeouts and one total attempt to
surface connectivity errors promptly. These are per-network-operation limits, not
an absolute invocation deadline (DNS and multiple addresses can take longer).
Database connection timeout remains 5 seconds; statement and lock timeouts remain
8 and 5 seconds. Credentials continue to be cached for 60 seconds, so warm requests
may skip secret retrieval. No write transactions are automatically retried.

API Gateway access logs additionally include integration latency and integration
error message. If the Lambda has no invocation log for the Gateway request, inspect
those fields, the integration target and Lambda invocation permission.

Share the failed phase, error type/SQLSTATE, request ID and final `REPORT` line for
further diagnosis. Do not share credentials or tokens.

References: [Lambda execution lifecycle](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html),
[SDK timeout configuration](https://docs.aws.amazon.com/botocore/latest/reference/config.html).

## Other Lambda functions

OutboxPublisher uses the same database phases plus `eventbridge_client`,
`eventbridge_publish`, `eventbridge_result` and `outbox_result`. Inspect its own
log group for publish failures. EventBridge SDK calls also use 3-second connect/read
timeouts and one attempt; pending outbox records remain available for the next run.
The Cognito token-generation function logs start, completion, client match and
exception type without recording claims or token contents.
