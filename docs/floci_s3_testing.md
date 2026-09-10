# Optional Floci S3 testing

ZepGPU can use [Floci](https://github.com/floci-io/floci) as an optional local AWS
emulator for the existing S3 result-storage path. This covers bucket creation, result upload,
download, metadata and listing calls, deletion, and presigned GET and PUT URLs.

Floci is not a runtime dependency. ZepGPU does not start it automatically, and this integration
does not cover the EC2 GPU provider. Floci's EC2 emulator does not implement every operation used
by ZepGPU and its non-mock instances are Docker containers, not AWS GPU capacity.

## Start Floci

Run Floci separately using its official image:

```bash
docker run --rm --name zepgpu-floci -p 4566:4566 floci/floci:latest
```

Floci listens at `http://localhost:4566`. In another shell, configure the standard AWS SDK
environment:

```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_DEFAULT_REGION=us-east-1
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
```

PowerShell equivalent:

```powershell
$env:AWS_ENDPOINT_URL = "http://localhost:4566"
$env:AWS_DEFAULT_REGION = "us-east-1"
$env:AWS_ACCESS_KEY_ID = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
```

The credentials are dummy local values and must not be used for an AWS account.
ZepGPU preserves its existing `S3__ACCESS_KEY`, `S3__SECRET_KEY`, and `S3__REGION` behavior,
including the legacy local defaults. Floci accepts those non-empty legacy credentials. The standard
AWS variables above are also useful for AWS CLI commands against the same Floci instance.

## Run the integration test

```bash
poetry run pytest tests/integration/test_floci_s3.py -m floci -v
```

The test uses the real ZepGPU `StorageClient`, creates a unique bucket, exercises the supported
result and presigned-URL operations, and removes its objects and bucket. It skips within one second
when the endpoint is not configured, and uses a one-second health-request timeout when Floci is
unavailable.

`AWS_S3_ENDPOINT_URL` may be used instead of `AWS_ENDPOINT_URL` to scope the override to ZepGPU's
S3 client. `AWS_ENDPOINT_URL_S3`, the botocore service-specific form, is also accepted. Endpoint
precedence is `AWS_S3_ENDPOINT_URL`, `AWS_ENDPOINT_URL_S3`, `AWS_ENDPOINT_URL`, existing nested
`S3__ENDPOINT_URL`, then the existing `http://localhost:9000` default.

## Return to existing ZepGPU behavior

Stop Floci and remove the endpoint override from the shell:

```bash
unset AWS_ENDPOINT_URL AWS_S3_ENDPOINT_URL AWS_ENDPOINT_URL_S3
```

With no new AWS endpoint override, ZepGPU retains its previous S3/MinIO behavior: the configured
nested `S3__*` values take effect, otherwise the client uses `http://localhost:9000`, the existing
local credentials, and `us-east-1`. This Floci integration does not redesign those defaults.

Floci is intended for API compatibility testing. Its default authentication is permissive and is
not a substitute for testing production IAM policies or real AWS authorization.
