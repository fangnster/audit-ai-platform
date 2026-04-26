import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from app.database import engine
from app.main import app


@pytest_asyncio.fixture
async def client():
    await engine.dispose()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_and_login(client):
    email = f"test-{uuid.uuid4().hex}@example.com"

    # Register
    r = await client.post("/api/v1/auth/register", json={
        "email": email,
        "name": "Test User",
        "password": "password123",
        "org_name": "Test Law Group",
    })
    assert r.status_code == 201
    assert r.json()["email"] == email

    # Login
    r = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": "password123",
    })
    assert r.status_code == 200
    assert "access_token" in r.json()

    token = r.json()["access_token"]
    org = await client.get("/api/v1/orgs/me", headers={"Authorization": f"Bearer {token}"})
    assert org.status_code == 200
    assert org.json()["name"] == "Test Law Group"

    profile = await client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Test Lawyer", "phone": "+1 555 123 4567"},
    )
    assert profile.status_code == 200
    assert profile.json()["name"] == "Test Lawyer"
    assert profile.json()["profile"]["phone"] == "+1 555 123 4567"


@pytest.mark.asyncio
async def test_case_requires_contact_and_status_can_update(client):
    email = f"case-test-{uuid.uuid4().hex}@example.com"
    password = "password123"

    r = await client.post("/api/v1/auth/register", json={
        "email": email,
        "name": "Case Tester",
        "password": password,
        "org_name": "Case Test Law Group",
    })
    assert r.status_code == 201

    login = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    missing_contact = await client.post("/api/v1/cases", headers=headers, json={
        "title": "Missing Contact Case",
        "case_type": "EB1A",
    })
    assert missing_contact.status_code == 422

    case_res = await client.post("/api/v1/cases", headers=headers, json={
        "title": "Contact Case",
        "case_type": "EB1A",
        "client_phone": "+1 555 000 0000",
    })
    assert case_res.status_code == 201
    assert case_res.json()["client_phone"] == "+1 555 000 0000"

    case_id = case_res.json()["id"]
    status_res = await client.patch(
        f"/api/v1/cases/{case_id}/status",
        headers=headers,
        json={"status": "drafting"},
    )
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "drafting"

    contact_res = await client.patch(
        f"/api/v1/cases/{case_id}",
        headers=headers,
        json={
            "client_name": "Updated Client",
            "client_email": "updated-client@example.com",
            "client_phone": "+1 555 111 2222",
        },
    )
    assert contact_res.status_code == 200
    assert contact_res.json()["client_name"] == "Updated Client"
    assert contact_res.json()["client_email"] == "updated-client@example.com"
    assert contact_res.json()["client_phone"] == "+1 555 111 2222"


@pytest.mark.asyncio
async def test_case_resources_require_case_membership(client):
    password = "password123"

    owner_email = f"owner-{uuid.uuid4().hex}@example.com"
    intruder_email = f"intruder-{uuid.uuid4().hex}@example.com"

    await client.post("/api/v1/auth/register", json={
        "email": owner_email,
        "name": "Owner Lawyer",
        "password": password,
        "org_name": "Owner Law Group",
    })
    owner_login = await client.post("/api/v1/auth/login", data={"username": owner_email, "password": password})
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

    case_res = await client.post("/api/v1/cases", headers=owner_headers, json={
        "title": "Private Case",
        "case_type": "EB1A",
        "client_email": "private-client@example.com",
    })
    assert case_res.status_code == 201
    case_id = case_res.json()["id"]

    await client.post("/api/v1/auth/register", json={
        "email": intruder_email,
        "name": "Other Lawyer",
        "password": password,
        "org_name": "Other Law Group",
    })
    intruder_login = await client.post("/api/v1/auth/login", data={"username": intruder_email, "password": password})
    intruder_headers = {"Authorization": f"Bearer {intruder_login.json()['access_token']}"}

    document_list = await client.get(
        f"/api/v1/documents/cases/{case_id}/documents",
        headers=intruder_headers,
    )
    assert document_list.status_code == 404

    delete_case = await client.delete(f"/api/v1/cases/{case_id}", headers=intruder_headers)
    assert delete_case.status_code == 404
