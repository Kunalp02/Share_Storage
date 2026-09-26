# Platform auth

Python services use this to accept the same bearer token the .NET services already accept.

The .NET auth service issues that token. This library does not call `GET /api/v1/auth/me`. That route returns null for `sub` and `username` because the token stores those values as `nameid` and `unique_name`. Python reads those claims, plus `groups` and `role`, from the bearer token itself. An expired token is rejected.

`permissions` on `/me` are the token's `roles` claims (the permission codes). `groups` are the group ids. Set `AUTH_REQUIRED_PERMISSIONS` to a comma-separated list when a route must match a .NET `[Authorize(Roles = ...)]` gate. Leave it empty to allow any accepted platform user. Resource checks, such as whether the user may open a given agent, still happen in the existing config services with this same bearer.
