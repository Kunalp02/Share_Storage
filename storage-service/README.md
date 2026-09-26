# Storage service

Files for agent threads. Metadata is in Postgres. Bytes are in S3 or MinIO.

A thread id is the same value execution returns as `threadId` and `executionId`.

## Run

```bash
cp .env.example .env
pip install -e ".[dev]"
storage-service
```

The API listens on port 8770.

## Caller API

`POST /api/v1/agents/{agentId}/artifacts/init` with a user bearer token. If `threadId` is omitted, storage asks execution to open a thread.

`POST /api/v1/artifacts/{artifactId}/complete` after the client uploads to the presigned URL.

## Internal API

Execution calls these with `X-Internal-Api-Key`:

- `GET /api/v1/internal/artifacts/{artifactId}/content` reads text into the prompt
- `POST /api/v1/internal/threads/{threadId}/artifacts` stores a run output
- `DELETE /api/v1/internal/threads/{threadId}/artifacts` removes a thread during expiry

The internal key is empty by default, and empty keys are rejected.
