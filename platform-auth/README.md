# Platform auth

Python services use this to accept the same bearer token the .NET services already accept.

The .NET auth service issues that token and keeps the session. This library does not log anyone in and does not mint a second token. It calls `GET /api/v1/auth/me` with the caller's `Authorization` header. That route sits behind the same platform middleware as the .NET configuration APIs, so a token those APIs accept is accepted here, and a logged-out or rejected token is rejected here.

`permissions` on `/me` are the token's `roles` claims (the permission codes). `groups` are the group ids. Set `AUTH_REQUIRED_PERMISSIONS` to a comma-separated list when a route must match a .NET `[Authorize(Roles = ...)]` gate. Leave it empty to allow any accepted platform user. Resource checks, such as whether the user may open a given agent, still happen in the existing config services with this same bearer.
