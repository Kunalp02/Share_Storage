from __future__ import annotations

import base64
import json
import time

import pytest

from platform_auth import AuthError, PlatformTokenVerifier, parse_codes


def test_parse_codes_splits_comma_separated_claims():
    assert parse_codes(["1,2", "2", " 10 "]) == ("1", "2", "10")


def _token(payload: dict) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    body = _segment(payload)
    return f"{header}.{body}.signature"


def _segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.mark.asyncio
async def test_dotnet_claim_names_become_principal():
    token = _token(
        {
            "unique_name": "ada",
            "nameid": "user-1",
            "groups": "3672e739-c81b-4029-abae-8a563166c476",
            "role": ["9", "10"],
            "exp": int(time.time()) + 3600,
        }
    )
    verifier = PlatformTokenVerifier(required_permissions=("9",))
    principal = await verifier.authenticate(f"Bearer {token}")
    assert principal.username == "ada"
    assert principal.user_id == "user-1"
    assert principal.subject == "user-1"
    assert principal.groups == ("3672e739-c81b-4029-abae-8a563166c476",)
    assert principal.permissions == ("9", "10")
    assert principal.token == token
    await verifier.aclose()


@pytest.mark.asyncio
async def test_groups_only_token_is_accepted():
    token = _token({"groups": ["3672e739-c81b-4029-abae-8a563166c476"], "exp": int(time.time()) + 60})
    principal = await PlatformTokenVerifier().authenticate(f"Bearer {token}")
    assert principal.groups == ("3672e739-c81b-4029-abae-8a563166c476",)
    assert principal.username == ""


@pytest.mark.asyncio
async def test_malformed_or_expired_token_is_unauthorized():
    verifier = PlatformTokenVerifier()
    with pytest.raises(AuthError) as malformed:
        await verifier.authenticate("Bearer not-a-platform-token")
    assert malformed.value.status_code == 401
    assert malformed.value.code == "UNAUTHORIZED"
    expired = _token({"unique_name": "ada", "exp": int(time.time()) - 10})
    with pytest.raises(AuthError) as old:
        await verifier.authenticate(f"Bearer {expired}")
    assert old.value.message == "Platform token has expired."
    await verifier.aclose()


@pytest.mark.asyncio
async def test_missing_permission_is_forbidden():
    token = _token({"unique_name": "ada", "permissions": ["1"], "exp": int(time.time()) + 60})
    verifier = PlatformTokenVerifier(required_permissions=("9",))
    with pytest.raises(AuthError) as caught:
        await verifier.authenticate(f"Bearer {token}")
    assert caught.value.status_code == 403
    assert caught.value.code == "FORBIDDEN"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_blank_token():
    with pytest.raises(AuthError) as missing:
        await PlatformTokenVerifier().authenticate(None)
    assert missing.value.code == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_cache_reuses_principal():
    token = _token({"unique_name": "ada", "exp": int(time.time()) + 60})
    verifier = PlatformTokenVerifier(cache_ttl_seconds=60)
    first = await verifier.authenticate(f"Bearer {token}")
    second = await verifier.authenticate(f"Bearer {token}")
    assert first.username == second.username == "ada"
    await verifier.aclose()
