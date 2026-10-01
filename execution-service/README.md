# Execution service

Runtime for studio test chats and the published agent API. Agent definitions stay in Agent Config. This service runs them.

## Concepts

- A **thread** is one conversation. Its retention policy is also the memory retention policy. When the thread expires, that conversation is deleted with it.
- A **run** is one message on that thread. A normal call finishes inside the API process. `background: true` queues a job for the worker.
- A **deployment** is the published endpoint for one agent. It returns an API key and the chat URL. Calling it again returns the same key. If the stored key cannot be read, a new key is issued and `keyReissued` is true.

## Run

```bash
cp .env.example .env
pip install -e "../platform-auth" -e ".[dev]"
agent-execution
agent-execution-worker
```

The API listens on port 8765. `GET /api/v1/health/live` is the process check. `GET /api/v1/health/ready` checks the database.

Logs include `requestId` on every line. Send `X-Request-ID` to correlate a call, or read the id the service returns. Set `LOG_FORMAT=json` in production. The log line never includes the user message, bearer token, or API key.

## How a message is executed

The API process and the worker process share the same database. They do different jobs.

1. `POST /test` or `POST /chat` opens or continues a thread, then inserts a run.
2. A normal run (`background` omitted or false) is executed by the API process that received the request. The process holds a lease and a heartbeat so a crash is visible. At most `MAX_INFLIGHT_RUNS` runs execute in that process at once. Extra calls get `429`.
3. A background run is inserted as `QUEUED` and the HTTP call returns immediately. Postgres notifies the worker. The worker also polls, so a missed notification is still picked up. It claims with `FOR UPDATE SKIP LOCKED` and runs up to `MAX_INFLIGHT_RUNS` jobs at once. The claim sets `worker_id` and a lease. A heartbeat extends the lease while the model or tools are running. Success and failure updates match that `worker_id` and attempt, so a worker whose lease was stolen cannot overwrite the result.
4. A temporary failure (timeout, busy, or a dependency that is down) goes back to `QUEUED` after a short delay, until `RUN_MAX_ATTEMPTS`. A permanent failure, such as a context window that cannot fit, is `FAILED` on the first attempt. The run stores `errorCode` and `error` with the reason. `run.failed:<code>` is added to the steps. If the API process dies, the reason is `RUN_INTERRUPTED`. If a background worker dies and no attempts remain, the reason is `WORKER_LOST`.
5. A separate loop deletes conversation memory whose expiry has passed and expires threads whose retention has passed. The worker writes `worker_heartbeats`. `GET /api/v1/workers` with a platform token lists each worker, when it was last seen, and whether it is still alive.

Start `agent-execution` and `agent-execution-worker` as two processes. The worker does not serve HTTP.

## Studio test

`POST /api/v1/agents/{agentId}/test` with the platform bearer token and `{ "input": "hello" }`.

The agent does not have to be published. The call uses the current draft, opens a test thread when `threadId` is omitted, and returns that `threadId` with the answer. Send the same `threadId` on the next call to continue the conversation. Test threads, and their memory, expire after `TEST_THREAD_TTL_HOURS` (24 by default).

`POST /api/v1/agents/{agentId}/threads/{threadId}/runs` remains for a thread that was opened separately. `GET /api/v1/agents/{agentId}/threads` lists them for the activity page.

Send the same `Authorization: Bearer` token the .NET configuration APIs accept. Execution reads the user from that token (`unique_name`, `nameid`, `groups`, `role`) and does not call `GET /api/v1/auth/me`. The same token is then forwarded to Agent Config, which still decides whether that user can see the agent.

Set `AUTH_REQUIRED_PERMISSIONS` to comma-separated permission codes when a studio route must match a .NET role gate. Leave it empty to allow every token that is still inside its expiry.

## Published chat

`POST /api/v1/agents/{agentId}/deployments` with a user token. Body can be `{}`. The agent must already be published. The response always includes `apiKey` and `chatUrl`.

`chatUrl` is `POST /api/v1/agents/{agentId}/chat`. Callers send `X-Api-Key`.

```json
{ "input": "hello" }
```

Omit `threadId` to start a conversation. The response includes `threadId`. Send it back to continue. Memory for that conversation is deleted on the same schedule as the thread (`retentionPolicy` on the deployment: `TEMPORARY`, `30_DAYS`, `90_DAYS`, `1_YEAR`, or `PERMANENT`).

`GET /api/v1/agents/{agentId}/chat/runs/{runId}` with the same API key reads a background run.

`POST /api/v1/agents/{agentId}/deployments/{deploymentId}/rotate` issues a new key and invalidates the previous one.

Set `API_KEY_ENCRYPTION_SECRET` to a private value. The key is stored encrypted, so listing deployments can show it again. If an older row has no readable key, the next create or list issues a replacement and sets `keyReissued` to true.

## Context

`CONTEXT_WINDOW_TOKENS` is the model window. `CONTEXT_OUTPUT_RESERVE_TOKENS` is held back for the answer. The context manager fits the prompt into what remains. It keeps the system prompt and the new user message, and shortens attached files, then knowledge-base text, then older history. Those cuts are recorded on the run as `context.trimmed:files`, `context.trimmed:knowledge`, and `context.trimmed:history`. If knowledge-base search fails, the run records `rag.unavailable` and the model is told to answer without it. A failed tool is returned to the model as unavailable instead of failing the whole run, and the run records `tool.failed:<name>:<code>`.

## What Agent Config should add

Execution already calls these when they exist, and falls back to `GET /api/v1/agents/{id}/runtime-manifest` on 404:

- `GET /api/v1/agents/{id}/revisions/{revisionId}/runtime-manifest`
- `GET /api/v1/agents/{id}/revisions/current/runtime-manifest`

Until those exist, a production thread snapshots whatever the current runtime manifest returns, and that snapshot must already be `Published`.
