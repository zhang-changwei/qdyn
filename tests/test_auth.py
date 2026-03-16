import os
import tempfile

import pytest

from src.auth.database import (
    init_db,
    get_db,
    create_user,
    get_user,
    assign_task,
    get_user_tasks,
    get_task_owner,
    get_task_job_ids,
    delete_task_record,
)
from src.auth.security import (
    configure,
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_auth():
    """Initialise a fresh temp DB and configure security for every test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    configure("test-secret-key-long-enough-for-hs256!!", 24)
    yield
    os.unlink(path)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("hello123")
        assert verify_password("hello123", h)

    def test_wrong_password(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salts differ


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------


class TestJWT:
    def test_roundtrip(self):
        token = create_access_token("alice")
        assert decode_token(token) == "alice"

    def test_invalid_token(self):
        import jwt

        with pytest.raises(jwt.PyJWTError):
            decode_token("not.a.valid.token")

    def test_wrong_secret(self):
        import jwt as pyjwt

        token = create_access_token("alice")
        # reconfigure with a different secret
        configure("different-secret-key-long-enough-for-hs256!!", 24)
        with pytest.raises(pyjwt.PyJWTError):
            decode_token(token)


# ---------------------------------------------------------------------------
# Database — users
# ---------------------------------------------------------------------------


class TestDatabaseUsers:
    def test_create_and_get_user(self):
        conn = get_db()
        create_user(conn, "bob", "hashed_pw_value")
        user = get_user(conn, "bob")
        assert user is not None
        assert user["username"] == "bob"
        assert user["hashed_pw"] == "hashed_pw_value"

    def test_get_nonexistent_user(self):
        conn = get_db()
        assert get_user(conn, "ghost") is None

    def test_duplicate_user_raises(self):
        conn = get_db()
        create_user(conn, "dup", "pw")
        with pytest.raises(Exception):
            create_user(conn, "dup", "pw2")


# ---------------------------------------------------------------------------
# Database — task ownership
# ---------------------------------------------------------------------------


class TestDatabaseTasks:
    def test_assign_and_list_tasks(self):
        conn = get_db()
        create_user(conn, "alice", "pw")
        assign_task(conn, "t1", "alice", {"nvt": ["uuid-1"]})
        assign_task(conn, "t2", "alice", {"nve": ["uuid-2", "uuid-3"]})
        tasks = get_user_tasks(conn, "alice")
        assert set(tasks) == {"t1", "t2"}

    def test_get_task_owner(self):
        conn = get_db()
        create_user(conn, "bob", "pw")
        assign_task(conn, "t5", "bob", {})
        assert get_task_owner(conn, "t5") == "bob"
        assert get_task_owner(conn, "nonexistent") is None

    def test_get_task_job_ids(self):
        conn = get_db()
        create_user(conn, "carol", "pw")
        jobs = {"scf": ["a", "b"], "namd": ["c"]}
        assign_task(conn, "t6", "carol", jobs)
        assert get_task_job_ids(conn, "t6") == jobs

    def test_delete_task(self):
        conn = get_db()
        create_user(conn, "dave", "pw")
        assign_task(conn, "t7", "dave", {})
        delete_task_record(conn, "t7")
        assert get_task_owner(conn, "t7") is None
        assert get_user_tasks(conn, "dave") == []

    def test_user_isolation(self):
        conn = get_db()
        create_user(conn, "alice", "pw")
        create_user(conn, "bob", "pw")
        assign_task(conn, "ta", "alice", {})
        assign_task(conn, "tb", "bob", {})
        assert get_user_tasks(conn, "alice") == ["ta"]
        assert get_user_tasks(conn, "bob") == ["tb"]
        assert get_task_owner(conn, "ta") == "alice"
        assert get_task_owner(conn, "tb") == "bob"


# ---------------------------------------------------------------------------
# Auth router (via FastAPI TestClient)
# ---------------------------------------------------------------------------


class TestAuthRouter:
    """Test /auth/register and /auth/login via a lightweight test app."""

    @pytest.fixture()
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.auth.router import router

        test_app = FastAPI()
        test_app.include_router(router)
        return TestClient(test_app)

    def test_register(self, client):
        resp = client.post(
            "/auth/register",
            json={"username": "newuser", "password": "secret"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # token should be valid
        username = decode_token(data["access_token"])
        assert username == "newuser"

    def test_register_duplicate(self, client):
        client.post(
            "/auth/register",
            json={"username": "dup", "password": "pw"},
        )
        resp = client.post(
            "/auth/register",
            json={"username": "dup", "password": "pw2"},
        )
        assert resp.status_code == 409

    def test_login_success(self, client):
        client.post(
            "/auth/register",
            json={"username": "loginuser", "password": "mypass"},
        )
        resp = client.post(
            "/auth/login",
            json={"username": "loginuser", "password": "mypass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert decode_token(data["access_token"]) == "loginuser"

    def test_login_wrong_password(self, client):
        client.post(
            "/auth/register",
            json={"username": "u1", "password": "right"},
        )
        resp = client.post(
            "/auth/login",
            json={"username": "u1", "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post(
            "/auth/login",
            json={"username": "nobody", "password": "x"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Protected endpoints (dependency injection test)
# ---------------------------------------------------------------------------


class TestProtectedEndpoints:
    """Test that auth dependency correctly protects endpoints."""

    @pytest.fixture()
    def protected_client(self):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from src.auth.dependencies import get_current_user
        from src.auth.router import router

        test_app = FastAPI()
        test_app.include_router(router)

        @test_app.get("/protected")
        def protected(username: str = Depends(get_current_user)):
            return {"user": username}

        return TestClient(test_app)

    def _register_and_get_token(self, client, username="testuser", password="pw"):
        resp = client.post(
            "/auth/register",
            json={"username": username, "password": password},
        )
        return resp.json()["access_token"]

    def test_access_with_valid_token(self, protected_client):
        token = self._register_and_get_token(protected_client)
        resp = protected_client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["user"] == "testuser"

    def test_access_without_token(self, protected_client):
        resp = protected_client.get("/protected")
        assert resp.status_code in (401, 403)  # depends on FastAPI version

    def test_access_with_invalid_token(self, protected_client):
        resp = protected_client.get(
            "/protected", headers={"Authorization": "Bearer garbage.token.here"}
        )
        assert resp.status_code == 401

    def test_user_isolation(self, protected_client):
        token_a = self._register_and_get_token(protected_client, "alice", "pw1")
        token_b = self._register_and_get_token(protected_client, "bob", "pw2")
        resp_a = protected_client.get(
            "/protected", headers={"Authorization": f"Bearer {token_a}"}
        )
        resp_b = protected_client.get(
            "/protected", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert resp_a.json()["user"] == "alice"
        assert resp_b.json()["user"] == "bob"
