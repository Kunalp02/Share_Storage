from __future__ import annotations

import httpx
import pytest

from platform_auth import AuthError, PlatformTokenVerifier, parse_codes


def test_parse_codes_splits_comma_separated_claims():
    assert parse_codes(["1,2", "2", " 10 "]) == ("1", "2", "10")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="http://auth", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_me_response_becomes_principal():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/me"
        assert request.headers["authorization"] == "Bearer platform-token"
        return httpx.Response(
            200,
            json={
                "sub": "user-1",
                "username": "ada",
                "groups": ["3,4"],
                "permissions": ["9,10"],
            },
        )

    verifier = PlatformTokenVerifier(configured=True, http=_client(handler), required_permissions=("9",))
    principal = await verifier.authenticate("Bearer platform-token")
    assert principal.username == "ada"
    assert principal.user_id == "user-1"
    assert principal.groups == ("3", "4")
    assert principal.permissions == ("9", "10")
    assert principal.token == "platform-token"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_rejected_token_is_unauthorized():
    verifier = PlatformTokenVerifier(
        configured=True,
        http=_client(lambda request: httpx.Response(401)),
    )
    with pytest.raises(AuthError) as caught:
        await verifier.authenticate("Bearer nope")
    assert caught.value.status_code == 401
    assert caught.value.code == "UNAUTHORIZED"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_missing_permission_is_forbidden():
    verifier = PlatformTokenVerifier(
        configured=True,
        http=_client(lambda request: httpx.Response(200, json={"sub": "u", "username": "ada", "permissions": ["1"]})),
        required_permissions=("9",),
    )
    with pytest.raises(AuthError) as caught:
        await verifier.authenticate("Bearer token")
    assert caught.value.status_code == 403
    assert caught.value.code == "FORBIDDEN"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_unreachable_auth_service():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    verifier = PlatformTokenVerifier(configured=True, http=_client(handler))
    with pytest.raises(AuthError) as caught:
        await verifier.authenticate("Bearer token")
    assert caught.value.code == "AUTH_UNAVAILABLE"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_blank_token_and_unconfigured_service():
    verifier = PlatformTokenVerifier(configured=False, http=_client(lambda request: httpx.Response(500)))
    with pytest.raises(AuthError) as missing:
        await verifier.authenticate(None)
    assert missing.value.code == "UNAUTHORIZED"
    with pytest.raises(AuthError) as unconfigured:
        await verifier.authenticate("Bearer token")
    assert unconfigured.value.code == "AUTH_NOT_CONFIGURED"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_cache_skips_second_me_call():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"sub": "u", "username": "ada", "permissions": []})

    verifier = PlatformTokenVerifier(configured=True, http=_client(handler), cache_ttl_seconds=60)
    first = await verifier.authenticate("Bearer same")
    second = await verifier.authenticate("Bearer same")
    assert first.username == second.username == "ada"
    assert calls["count"] == 1
    await verifier.aclose()
