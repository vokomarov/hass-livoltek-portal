"""Auth owns the credentials, the cached 30-day token, and its decoded expiry."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientSession
from aioresponses import CallbackResult, aioresponses

from custom_components.livoltek_portal.api.auth import (
    FALLBACK_TOKEN_TTL,
    LivoltekAuth,
    decode_token_expiry,
    hash_password,
)
from custom_components.livoltek_portal.api.errors import (
    LivoltekAuthError,
    LivoltekCaptchaRequiredError,
    LivoltekConnectionError,
)
from custom_components.livoltek_portal.api.models import Session

BASE_URL = "https://evs.livoltek-portal.test"
LOGIN_URL = f"{BASE_URL}/nbp/login/customer"


def make_token(exp: datetime) -> str:
    """Build an unsigned HS512-shaped JWT. The signature is never verified."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS512"}').rstrip(b"=").decode()
    claims = json.dumps(
        {
            "sub": "u",
            "tokenId": "t",
            "iat": int(exp.timestamp()) - 2_592_000,
            "exp": int(exp.timestamp()),
        }
    ).encode()
    body = base64.urlsafe_b64encode(claims).rstrip(b"=").decode()
    return f"{header}.{body}.signature"


def login_envelope(token: str, owner_id: str = "9001") -> dict:
    return {
        "code": None,
        "data": {"id": "s1", "access_token": token, "owner": {"id": owner_id}},
        "message": None,
        "msg_code": "operate.success",
    }


def test_password_is_lowercase_md5_hex() -> None:
    """The API accepts md5(password); sending the plaintext returns err.password."""
    assert hash_password("password") == "5f4dcc3b5aa765d61d8327deb882cf99"
    assert len(hash_password("anything")) == 32
    assert hash_password("ABC") == hash_password("ABC").lower()


def test_session_repr_never_shows_the_token() -> None:
    """A bearer token must not leak into a traceback or a formatted log line."""
    token = make_token(datetime.now(UTC) + timedelta(days=30))
    session = Session(access_token=token, expires_at=datetime.now(UTC), owner_id="9001")
    assert token not in repr(session)


def test_decode_token_expiry_reads_the_exp_claim() -> None:
    expected = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)
    assert decode_token_expiry(make_token(expected)) == expected


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not.a.jwt",
        "a.b",
        "a.b.c.d",
        "x.!!!not-base64!!!.y",
        "x." + base64.urlsafe_b64encode(b'{"no":"exp"}').decode() + ".y",
        # A JSON `true` is a bool, which is also an int subclass in Python;
        # it must not be accepted as a timestamp.
        "x." + base64.urlsafe_b64encode(b'{"exp":true}').decode() + ".y",
    ],
)
def test_malformed_tokens_decode_to_none(token: str) -> None:
    """A token whose expiry cannot be read is treated as already expired."""
    assert decode_token_expiry(token) is None


async def test_login_posts_the_wire_shape_including_the_typo() -> None:
    token = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload=login_envelope(token))
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "user@example.com", "abc123")
            result = await auth.async_login()

    request = next(iter(mocked.requests.values()))[0]
    body = request.kwargs["json"]
    assert body["login_account"] == "user@example.com"
    assert body["password"] == "abc123"
    assert body["acctount_type"] == "email"  # the API's typo, reproduced verbatim
    assert body["device_name"] == "Home Assistant"
    assert body["device_type"] == 0
    assert body["language"] == "en"
    assert "image_id" not in body
    assert result.access_token == token
    assert result.owner_id == "9001"


async def test_login_includes_the_captcha_when_supplied() -> None:
    token = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload=login_envelope(token))
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "u", "p")
            await auth.async_login(image_id="i-1", image_code="4H2K")

    body = next(iter(mocked.requests.values()))[0].kwargs["json"]
    assert body["image_id"] == "i-1"
    assert body["image_code"] == "4H2K"


async def test_login_propagates_a_captcha_lockout() -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload={"msg_code": "err.password.need.verify"})
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "u", "p")
            with pytest.raises(LivoltekCaptchaRequiredError):
                await auth.async_login()


async def test_login_propagates_a_wrong_password() -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload={"msg_code": "err.password"})
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "u", "p")
            with pytest.raises(LivoltekAuthError):
                await auth.async_login()


async def test_login_without_an_access_token_is_a_connection_error() -> None:
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload={"data": {}, "msg_code": "operate.success"})
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "u", "p")
            with pytest.raises(LivoltekConnectionError):
                await auth.async_login()


async def test_an_unparseable_fresh_token_gets_a_fallback_ttl() -> None:
    """A freshly issued token we cannot decode must not re-login on every poll."""
    before = datetime.now(UTC)
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload=login_envelope("opaque-token"))
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "u", "p")
            await auth.async_login()
    assert auth.expires_at is not None
    assert auth.expires_at >= before + FALLBACK_TOKEN_TTL


async def test_a_valid_cached_token_is_reused_without_logging_in() -> None:
    token = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        async with ClientSession() as session:
            auth = LivoltekAuth(
                session,
                BASE_URL,
                "u",
                "p",
                token=token,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            assert await auth.async_get_token() == token
    assert not mocked.requests


async def test_a_token_inside_the_refresh_margin_is_replaced() -> None:
    """Re-login happens proactively at exp - 3 days, not at exp."""
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload=login_envelope(fresh))
        async with ClientSession() as session:
            auth = LivoltekAuth(
                session,
                BASE_URL,
                "u",
                "p",
                token="stale",
                expires_at=datetime.now(UTC) + timedelta(days=2),
            )
            assert await auth.async_get_token() == fresh
    assert len(next(iter(mocked.requests.values()))) == 1


async def test_a_token_with_no_known_expiry_is_treated_as_expired() -> None:
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload=login_envelope(fresh))
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "u", "p", token="x", expires_at=None)
            assert await auth.async_get_token() == fresh


async def test_invalidate_forces_the_next_call_to_log_in() -> None:
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, payload=login_envelope(fresh))
        async with ClientSession() as session:
            auth = LivoltekAuth(
                session,
                BASE_URL,
                "u",
                "p",
                token="old",
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            auth.invalidate()
            assert await auth.async_get_token() == fresh


async def test_concurrent_callers_produce_exactly_one_login() -> None:
    """N device coordinators starting together must not fire N logins.

    aioresponses' mocked transport completes a request without a genuine
    await-on-unresolved-future checkpoint, so a naive `asyncio.gather` over
    `async_get_token()` degenerates into sequential execution: the winner
    finishes its whole login and caches the token before the next caller even
    starts, so every "waiter" is satisfied by the lock-free fast path and the
    re-check-under-lock branch is never exercised. To prove single-flight for
    real, the mocked login blocks (via an Event) until every caller has
    arrived, forcing the late callers to genuinely queue on the lock; a
    counter incremented only when the re-check finds an already-fresh token
    while holding the lock proves that branch, not scheduling luck, is what
    produced the shared result.
    """
    concurrency = 8
    fresh = make_token(datetime.now(UTC) + timedelta(days=30))
    arrivals = 0
    all_arrived = asyncio.Event()
    recheck_hits = 0

    async def login_callback(url: str, **kwargs: object) -> CallbackResult:
        # Hold the winner's login open until every caller has had a chance to
        # reach async_get_token and queue on the lock.
        await all_arrived.wait()
        return CallbackResult(payload=login_envelope(fresh))

    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, callback=login_callback, repeat=True)
        async with ClientSession() as session:
            auth = LivoltekAuth(session, BASE_URL, "u", "p")
            original_is_stale = auth._is_stale

            def spying_is_stale() -> bool:
                nonlocal recheck_hits
                stale = original_is_stale()
                if auth._lock.locked() and not stale:
                    recheck_hits += 1
                return stale

            auth._is_stale = spying_is_stale

            async def tracked_call() -> str:
                nonlocal arrivals
                arrivals += 1
                if arrivals == concurrency:
                    all_arrived.set()
                return await auth.async_get_token()

            tokens = await asyncio.gather(*(tracked_call() for _ in range(concurrency)))

    assert tokens == [fresh] * concurrency
    assert len(next(iter(mocked.requests.values()))) == 1
    # Every caller but the winner must have taken the cache-hit branch under
    # the lock; deleting that branch drops this to 0 (and breaks the login
    # count above too, since every waiter would then log in for itself).
    assert recheck_hits == concurrency - 1
