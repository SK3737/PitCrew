"""
End-to-end auth flow: register -> login -> protected route access (allowed,
unauthenticated, wrong role) -> refresh rotation -> reuse detection.

Uses ``async_client`` (httpx.AsyncClient over ASGITransport) rather than the
sync TestClient because it needs a real, session-persisted cookie jar to
exercise the HttpOnly refresh cookie the way a browser would.
"""

import uuid

PASSWORD = "correct horse battery staple"


async def _register_and_login(async_client, role: str) -> tuple[str, dict]:
    email = f"{role}-{uuid.uuid4()}@example.com"
    await async_client.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "role": role}
    )
    login = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    access_token = login.json()["access_token"]
    return access_token, {"Authorization": f"Bearer {access_token}"}


async def test_protected_route_allows_correct_role(async_client):
    _, headers = await _register_and_login(async_client, "mechanic")

    r = await async_client.post(
        "/predict", json={"months_driven": 5, "total_kms_driven": 7200}, headers=headers
    )

    assert r.status_code == 200


async def test_protected_route_rejects_missing_token(async_client):
    r = await async_client.post("/predict", json={"months_driven": 5, "total_kms_driven": 7200})

    assert r.status_code == 401


async def test_protected_route_rejects_wrong_role(async_client):
    # "owner" role has no run_predict permission per the RBAC map.
    _, owner_headers = await _register_and_login(async_client, "owner")

    r = await async_client.post(
        "/predict", json={"months_driven": 5, "total_kms_driven": 7200}, headers=owner_headers
    )

    assert r.status_code == 403


async def test_login_never_puts_refresh_token_in_the_response_body(async_client):
    email = f"mechanic-{uuid.uuid4()}@example.com"
    await async_client.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "role": "mechanic"}
    )

    login = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})

    assert login.status_code == 200
    body = login.json()
    assert set(body.keys()) == {"access_token", "token_type"}
    assert "refresh" not in str(body).lower()

    cookie = login.cookies.get("refresh_token")
    assert cookie is not None


async def test_refresh_rotates_token_and_rejects_reuse_of_the_old_one(async_client):
    email = f"mechanic-{uuid.uuid4()}@example.com"
    await async_client.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "role": "mechanic"}
    )
    login = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    old_refresh_cookie = async_client.cookies.get("refresh_token")
    assert old_refresh_cookie is not None

    refreshed = await async_client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert "refresh_token" not in refreshed.json()
    new_access_token = refreshed.json()["access_token"]
    assert new_access_token != login.json()["access_token"]

    new_refresh_cookie = async_client.cookies.get("refresh_token")
    assert new_refresh_cookie is not None
    assert new_refresh_cookie != old_refresh_cookie

    # Replay the OLD (already-rotated) refresh token, as a thief who stole an
    # earlier cookie would - this must be rejected.
    async_client.cookies.set("refresh_token", old_refresh_cookie)
    reuse_attempt = await async_client.post("/auth/refresh")
    assert reuse_attempt.status_code == 401

    # Reuse detection must burn the *entire* chain, not just the reused link -
    # so the token that WAS still valid (new_refresh_cookie) is now rejected too.
    async_client.cookies.set("refresh_token", new_refresh_cookie)
    also_rejected = await async_client.post("/auth/refresh")
    assert also_rejected.status_code == 401


async def test_logout_revokes_the_refresh_token(async_client):
    email = f"mechanic-{uuid.uuid4()}@example.com"
    await async_client.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "role": "mechanic"}
    )
    await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})

    logout = await async_client.post("/auth/logout")
    assert logout.status_code == 204

    refresh_after_logout = await async_client.post("/auth/refresh")
    assert refresh_after_logout.status_code == 401
