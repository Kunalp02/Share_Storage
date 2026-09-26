# Agent platform runtime

Two services:

- `execution-service` runs agent threads and turns.
- `storage-service` stores files for those threads.

Agent, tool, knowledge-base, and model configuration stay in their existing services. Copy each `.env.example` to `.env` and fill in the URLs and secrets there. Do not commit those files.

Start the execution API, the execution worker, and the storage API as three processes. See each service README for routes.
