# Execution service

Runtime for studio test chats and the published agent API. Agent definitions stay in Agent Config. This service runs them.

## Concepts

- A **thread** is one conversation. Test threads expire. Production threads keep the manifest captured when the thread opened.
- A **run** is one message on that thread. Interactive runs finish on the HTTP request. `background: true` queues a run for the worker.
- A **deployment** publishes a slug and an API key. External apps call `/api/v1/invoke/{slug}` and can only run a published agent.

## Run

```bash
cp .env.example .env
pip install -e ".[dev]"
agent-execution
agent-execution-worker
```

The API listens on port 8765. Run the worker as a second process. It claims queued runs, extends leases, marks interrupted sync runs as failed, and expires old threads.

## Studio

`POST /api/v1/agents/{agentId}/threads` with `{ "executionType": "TEST" }` or `"PRODUCTION"`.

`POST /api/v1/agents/{agentId}/threads/{threadId}/runs` with `{ "input": "...", "inputArtifactIds": [], "stream": false, "background": false }`.

A bearer token is required. Agent Config still decides whether that user can see the agent.

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
