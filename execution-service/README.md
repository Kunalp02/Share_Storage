# Execution service

Runtime for studio test chats and the published agent API. Agent definitions stay in Agent Config. This service runs them.

## Concepts

- A **thread** is one conversation. Test threads expire. Production threads keep the manifest captured when the thread opened.
- A **run** is one message on that thread. Interactive runs finish on the HTTP request. `background: true` queues a run for the worker.
- A **deployment** publishes a slug and an API key. External apps call `/api/v1/invoke/{slug}` and can only run a published agent.

## Run

```bash
cp .env.example .env
pip install -e "../platform-auth" -e ".[dev]"
agent-execution
agent-execution-worker
```

The API listens on port 8765. `GET /api/v1/health/live` is the process check. `GET /api/v1/health/ready` checks the database.

Logs include `requestId` on every line. Send `X-Request-ID` to correlate a call, or read the id the service returns. Set `LOG_FORMAT=json` in production. The log line never includes the user message, bearer token, or API key.

Run the worker as a second process. It claims queued runs, extends leases, marks interrupted sync runs as failed, and expires old threads.

## Studio

`POST /api/v1/agents/{agentId}/threads` with `{ "executionType": "TEST" }` or `"PRODUCTION"`.

`POST /api/v1/agents/{agentId}/threads/{threadId}/runs` with `{ "input": "...", "inputArtifactIds": [], "stream": false, "background": false }`.

Send the same `Authorization: Bearer` token the .NET configuration APIs accept. Execution asks `GET /api/v1/auth/me` on the auth service before it does any work. A rejected or logged-out token stops here. The same token is then forwarded to Agent Config, which still decides whether that user can see the agent.

Set `AUTH_REQUIRED_PERMISSIONS` to comma-separated permission codes when a studio route must match a .NET role gate. Leave it empty to allow every accepted platform user. `AUTH_PRINCIPAL_CACHE_SECONDS=0` checks the auth service on every call, so logout is visible immediately.

## Published API

`POST /api/v1/agents/{agentId}/deployments` with a user token and `{ "slug": "claims-bot" }`. The response includes `apiKey` once.

External callers send `X-Api-Key`:

- `POST /api/v1/invoke/{slug}/threads`
- `POST /api/v1/invoke/{slug}/threads/{threadId}/messages`
- `POST /api/v1/invoke/{slug}` for a one-shot call
- `GET /api/v1/invoke/{slug}/runs/{runId}`

## What Agent Config should add

Execution already calls these when they exist, and falls back to `GET /api/v1/agents/{id}/runtime-manifest` on 404:

- `GET /api/v1/agents/{id}/revisions/{revisionId}/runtime-manifest`
- `GET /api/v1/agents/{id}/revisions/current/runtime-manifest`

Until those exist, a production thread snapshots whatever the current runtime manifest returns, and that snapshot must already be `Published`.
