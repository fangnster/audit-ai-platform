import uuid
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.middleware.auth import verify_password
from app.models.case import Case
from app.models.document import Document
from app.models.knowledge import KnowledgeItem
from app.models.user import User
from app.routers.documents import local_storage_path


@pytest_asyncio.fixture
async def client():
    await engine.dispose()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await engine.dispose()


async def register_and_login(client: AsyncClient, email: str, name: str = "Test User"):
    password = "password123"
    register = await client.post("/api/v1/auth/register", json={
        "email": email,
        "name": name,
        "password": password,
        "password_confirm": password,
        "firm_name": f"{name} Law Group",
    })
    assert register.status_code == 201

    login = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["firm_name"] == f"{name} Law Group"
    return headers, me.json()


async def promote_system_admin(email: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.is_system_admin = True
        user.is_active = True
        await db.commit()


async def create_case(client: AsyncClient, headers: dict[str, str], title: str):
    case_res = await client.post("/api/v1/cases", headers=headers, json={
        "title": title,
        "case_type": "EB1A",
        "client_email": f"{uuid.uuid4().hex}@client.example.com",
    })
    assert case_res.status_code == 201
    return case_res.json()


async def create_case_with_document(client: AsyncClient, headers: dict[str, str], title: str):
    case_id = (await create_case(client, headers, title))["id"]
    upload = await client.post(
        f"/api/v1/documents/cases/{case_id}/documents",
        headers=headers,
        data={"doc_type": "evidence"},
        files={"file": ("delete-me.txt", b"delete me", "text/plain")},
    )
    assert upload.status_code == 201
    doc = upload.json()
    local_path = local_storage_path(doc["storage_path"])
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(b"local fallback should be deleted")
    assert os.path.exists(local_path)
    return case_id, doc["id"], local_path


@pytest.mark.asyncio
async def test_admin_routes_require_system_admin(client):
    email = f"not-admin-{uuid.uuid4().hex}@example.com"
    headers, _user = await register_and_login(client, email, "Not Admin")

    overview = await client.get("/api/v1/admin/overview", headers=headers)
    delete = await client.delete(f"/api/v1/admin/cases/{uuid.uuid4()}", headers=headers)

    assert overview.status_code == 403
    assert delete.status_code == 403


@pytest.mark.asyncio
async def test_admin_bootstrap_from_configured_email(client):
    old_admins = settings.SYSTEM_ADMIN_EMAILS
    email = f"configured-admin-{uuid.uuid4().hex}@example.com"
    settings.SYSTEM_ADMIN_EMAILS = email
    try:
        headers, user = await register_and_login(client, email, "Configured Admin")
        assert user["is_system_admin"] is True

        overview = await client.get("/api/v1/admin/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["system_admins"] >= 1
    finally:
        settings.SYSTEM_ADMIN_EMAILS = old_admins


@pytest.mark.asyncio
async def test_admin_overview_user_search_and_recent_cases(client):
    admin_email = f"admin-{uuid.uuid4().hex}@example.com"
    lawyer_email = f"lawyer-{uuid.uuid4().hex}@example.com"

    admin_headers, _admin = await register_and_login(client, admin_email, "System Admin")
    await promote_system_admin(admin_email)
    lawyer_headers, lawyer = await register_and_login(client, lawyer_email, "Case Lawyer")

    case_res = await client.post("/api/v1/cases", headers=lawyer_headers, json={
        "title": "Admin Visible Case",
        "case_type": "EB1A",
        "client_email": "client@example.com",
    })
    assert case_res.status_code == 201

    overview = await client.get("/api/v1/admin/overview", headers=admin_headers)
    assert overview.status_code == 200
    data = overview.json()
    assert data["total_users"] >= 2
    assert data["active_cases"] >= 1
    assert data["total_cases"] >= 1
    assert any(item["email"] == lawyer_email for item in data["recent_users"])
    assert any(item["title"] == "Admin Visible Case" for item in data["recent_cases"])

    users = await client.get(
        "/api/v1/admin/users",
        headers=admin_headers,
        params={"q": "Case Lawyer Law Group", "page_size": 5},
    )
    assert users.status_code == 200
    user_items = users.json()["items"]
    assert any(
        item["id"] == lawyer["id"]
        and item["case_count"] >= 1
        and item["firm_name"] == "Case Lawyer Law Group"
        for item in user_items
    )

    recent_cases = await client.get("/api/v1/admin/cases/recent", headers=admin_headers)
    assert recent_cases.status_code == 200
    assert any(item["lead_lawyer_email"] == lawyer_email for item in recent_cases.json())


@pytest.mark.asyncio
async def test_admin_user_and_case_lists_support_pagination_and_sorting(client):
    token = uuid.uuid4().hex
    admin_email = f"admin-list-sort-{uuid.uuid4().hex}@example.com"
    heavy_email = f"heavy-{uuid.uuid4().hex}@example.com"
    medium_email = f"medium-{uuid.uuid4().hex}@example.com"
    empty_email = f"empty-{uuid.uuid4().hex}@example.com"

    admin_headers, _admin = await register_and_login(client, admin_email, "List Sort Admin")
    await promote_system_admin(admin_email)
    heavy_headers, _heavy = await register_and_login(client, heavy_email, f"Sort {token} Bravo")
    medium_headers, _medium = await register_and_login(client, medium_email, f"Sort {token} Charlie")
    await register_and_login(client, empty_email, f"Sort {token} Alpha")

    await create_case(client, heavy_headers, f"Admin Sort {token} Bravo")
    await create_case(client, heavy_headers, f"Admin Sort {token} Alpha")
    await create_case(client, medium_headers, f"Admin Sort {token} Charlie")

    users_page_1 = await client.get(
        "/api/v1/admin/users",
        headers=admin_headers,
        params={
            "q": token,
            "sort_by": "case_count",
            "sort_order": "desc",
            "page": 1,
            "page_size": 2,
        },
    )
    assert users_page_1.status_code == 200
    users_page_1_body = users_page_1.json()
    assert users_page_1_body["total"] == 3
    assert [item["case_count"] for item in users_page_1_body["items"]] == [2, 1]

    users_page_2 = await client.get(
        "/api/v1/admin/users",
        headers=admin_headers,
        params={
            "q": token,
            "sort_by": "case_count",
            "sort_order": "desc",
            "page": 2,
            "page_size": 2,
        },
    )
    assert users_page_2.status_code == 200
    assert [item["case_count"] for item in users_page_2.json()["items"]] == [0]

    cases_page_1 = await client.get(
        "/api/v1/admin/cases",
        headers=admin_headers,
        params={
            "q": f"Admin Sort {token}",
            "sort_by": "title",
            "sort_order": "asc",
            "page": 1,
            "page_size": 2,
        },
    )
    assert cases_page_1.status_code == 200
    cases_page_1_body = cases_page_1.json()
    assert cases_page_1_body["total"] == 3
    assert [item["title"] for item in cases_page_1_body["items"]] == [
        f"Admin Sort {token} Alpha",
        f"Admin Sort {token} Bravo",
    ]

    cases_page_2 = await client.get(
        "/api/v1/admin/cases",
        headers=admin_headers,
        params={
            "q": f"Admin Sort {token}",
            "sort_by": "title",
            "sort_order": "asc",
            "page": 2,
            "page_size": 2,
        },
    )
    assert cases_page_2.status_code == 200
    assert [item["title"] for item in cases_page_2.json()["items"]] == [f"Admin Sort {token} Charlie"]


@pytest.mark.asyncio
async def test_admin_user_toggles_and_lockout_guards(client):
    admin_email = f"admin-guard-{uuid.uuid4().hex}@example.com"
    lawyer_email = f"toggle-user-{uuid.uuid4().hex}@example.com"

    admin_headers, admin = await register_and_login(client, admin_email, "Guard Admin")
    await promote_system_admin(admin_email)
    _lawyer_headers, lawyer = await register_and_login(client, lawyer_email, "Toggle User")

    disable = await client.patch(
        f"/api/v1/admin/users/{lawyer['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert disable.status_code == 200
    assert disable.json()["is_active"] is False

    inactive_login = await client.post("/api/v1/auth/login", data={
        "username": lawyer_email,
        "password": "password123",
    })
    assert inactive_login.status_code == 401

    promote = await client.patch(
        f"/api/v1/admin/users/{lawyer['id']}",
        headers=admin_headers,
        json={"is_active": True, "is_system_admin": True},
    )
    assert promote.status_code == 200
    assert promote.json()["is_active"] is True
    assert promote.json()["is_system_admin"] is True

    lawyer_login = await client.post("/api/v1/auth/login", data={
        "username": lawyer_email,
        "password": "password123",
    })
    assert lawyer_login.status_code == 200
    lawyer_admin_headers = {"Authorization": f"Bearer {lawyer_login.json()['access_token']}"}
    lawyer_overview = await client.get("/api/v1/admin/overview", headers=lawyer_admin_headers)
    assert lawyer_overview.status_code == 200

    self_disable = await client.patch(
        f"/api/v1/admin/users/{admin['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert self_disable.status_code == 400

    self_demote = await client.patch(
        f"/api/v1/admin/users/{admin['id']}",
        headers=admin_headers,
        json={"is_system_admin": False},
    )
    assert self_demote.status_code == 400

    self_delete = await client.delete(f"/api/v1/admin/users/{admin['id']}", headers=admin_headers)
    assert self_delete.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_reset_user_password_without_exposing_old_password(client):
    admin_email = f"admin-reset-password-{uuid.uuid4().hex}@example.com"
    lawyer_email = f"reset-password-user-{uuid.uuid4().hex}@example.com"

    admin_headers, _admin = await register_and_login(client, admin_email, "Password Admin")
    await promote_system_admin(admin_email)
    lawyer_headers, lawyer = await register_and_login(client, lawyer_email, "Password User")

    forbidden = await client.patch(
        f"/api/v1/admin/users/{lawyer['id']}/password",
        headers=lawyer_headers,
        json={"new_password": "new-password-123", "new_password_confirm": "new-password-123"},
    )
    assert forbidden.status_code == 403

    mismatch = await client.patch(
        f"/api/v1/admin/users/{lawyer['id']}/password",
        headers=admin_headers,
        json={"new_password": "new-password-123", "new_password_confirm": "new-password-456"},
    )
    assert mismatch.status_code == 422

    too_short = await client.patch(
        f"/api/v1/admin/users/{lawyer['id']}/password",
        headers=admin_headers,
        json={"new_password": "short", "new_password_confirm": "short"},
    )
    assert too_short.status_code == 422

    reset = await client.patch(
        f"/api/v1/admin/users/{lawyer['id']}/password",
        headers=admin_headers,
        json={"new_password": "new-password-123", "new_password_confirm": "new-password-123"},
    )
    assert reset.status_code == 200
    assert reset.json() == {"message": "密码已重置"}
    assert "password" not in reset.text.lower()

    old_login = await client.post("/api/v1/auth/login", data={
        "username": lawyer_email,
        "password": "password123",
    })
    assert old_login.status_code == 401

    new_login = await client.post("/api/v1/auth/login", data={
        "username": lawyer_email,
        "password": "new-password-123",
    })
    assert new_login.status_code == 200

    async with AsyncSessionLocal() as db:
        target = await db.get(User, uuid.UUID(lawyer["id"]))
        assert target is not None
        assert verify_password("new-password-123", target.password_hash)
        assert "new-password-123" not in target.password_hash


@pytest.mark.asyncio
async def test_admin_delete_case_removes_records_and_stored_files(client):
    admin_email = f"admin-delete-case-{uuid.uuid4().hex}@example.com"
    lawyer_email = f"lawyer-delete-case-{uuid.uuid4().hex}@example.com"

    admin_headers, _admin = await register_and_login(client, admin_email, "Delete Case Admin")
    await promote_system_admin(admin_email)
    lawyer_headers, _lawyer = await register_and_login(client, lawyer_email, "Delete Case Lawyer")
    case_id, doc_id, local_path = await create_case_with_document(client, lawyer_headers, "Case To Delete")

    delete_res = await client.delete(f"/api/v1/admin/cases/{case_id}", headers=admin_headers)

    assert delete_res.status_code == 200
    body = delete_res.json()
    assert body["cases_deleted"] == 1
    assert body["documents_deleted"] == 1
    assert body["files_deleted"] >= 1
    assert not os.path.exists(local_path)

    async with AsyncSessionLocal() as db:
        assert await db.get(Case, uuid.UUID(case_id)) is None
        assert await db.get(Document, uuid.UUID(doc_id)) is None


@pytest.mark.asyncio
async def test_admin_delete_user_removes_owned_cases_knowledge_and_files(client):
    admin_email = f"admin-delete-user-{uuid.uuid4().hex}@example.com"
    lawyer_email = f"lawyer-delete-user-{uuid.uuid4().hex}@example.com"

    admin_headers, _admin = await register_and_login(client, admin_email, "Delete User Admin")
    await promote_system_admin(admin_email)
    lawyer_headers, lawyer = await register_and_login(client, lawyer_email, "Delete User Lawyer")
    case_id, doc_id, local_path = await create_case_with_document(client, lawyer_headers, "User Owned Case")

    knowledge = await client.post(
        "/api/v1/knowledge",
        headers=lawyer_headers,
        json={
            "title": "Delete user knowledge",
            "content": "private strategy",
            "item_type": "agent_strategy",
            "tags": ["delete"],
        },
    )
    assert knowledge.status_code == 201
    knowledge_id = knowledge.json()["id"]

    delete_res = await client.delete(f"/api/v1/admin/users/{lawyer['id']}", headers=admin_headers)

    assert delete_res.status_code == 200
    body = delete_res.json()
    assert body["users_deleted"] == 1
    assert body["cases_deleted"] == 1
    assert body["documents_deleted"] == 1
    assert body["knowledge_items_deleted"] >= 1
    assert body["files_deleted"] >= 1
    assert not os.path.exists(local_path)

    login = await client.post("/api/v1/auth/login", data={
        "username": lawyer_email,
        "password": "password123",
    })
    assert login.status_code == 401

    async with AsyncSessionLocal() as db:
        assert await db.get(User, uuid.UUID(lawyer["id"])) is None
        assert await db.get(Case, uuid.UUID(case_id)) is None
        assert await db.get(Document, uuid.UUID(doc_id)) is None
        assert await db.get(KnowledgeItem, uuid.UUID(knowledge_id)) is None
