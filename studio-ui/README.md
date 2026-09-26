# Studio UI

Browser for signing in and trying an agent. The page never talks to Keycloak. It posts the username and password to the .NET auth service, keeps the platform token in the browser session, and sends that token on later calls.

## What you can do

- **Activity** shows running, queued, and recently failed runs across the agents this user can open, plus who started each one.
- Sign in and see the user, groups, and permission codes returned by auth.
- List agents from Agent Config (`GET /api/v1/agents`). If that list is unavailable, paste an agent id.
- Open a test or production thread.
- Attach a text file, then send a message on that thread.
- Watch runs for the thread, including status, output, errors, steps, and file ids.

## Run

```bash
cp .env.example .env
npm install
npm run dev
```

The dev server listens on port 5173 and proxies:

- `/platform/auth` to `AUTH_SERVICE_URL`
- `/platform/agents` to `AGENT_CONFIG_URL`
- `/platform/execution` to `EXECUTION_SERVICE_URL`
- `/platform/storage` to `STORAGE_SERVICE_URL`

Point each URL at the host that already answers that service. If `curl http://172.19.204.37:8504/api/v1/agents` works, set `AGENT_CONFIG_URL=http://172.19.204.37:8504`. The browser still calls `http://127.0.0.1:5173/platform/agents/api/v1/agents`. A 500 on that address means the proxy target is down or still the default `127.0.0.1`. Restart `npm run dev` after editing `.env`.

The file bytes are uploaded from the browser to the presigned storage URL. MinIO must allow that browser origin on `PUT`.
