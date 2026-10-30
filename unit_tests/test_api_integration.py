
import os
import pytest
os.environ["INVITE_CODES"] = "TEST-OWNER-LONG-CODE-2026,SECOND-HOUSEHOLD-LONG-CODE"
os.environ["SECRET_SALT"] = "ci-test-production-salt-2026-secure"

from fastapi.testclient import TestClient
from app.main import app
from app.services.auth_limiter import _FAILED_ATTEMPTS


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_family_vault_role_assignment_and_viewer_restrictions(client):
    _FAILED_ATTEMPTS.clear()
    owner_headers = {"X-Invite-Code": "TEST-OWNER-LONG-CODE-2026"}

    res_member = client.post(
        "/api/v1/vault/members",
        headers=owner_headers,
        json={"member_id": "mom", "display_name": "Amma", "relationship": "Mother"},
    )
    assert res_member.status_code == 200

    # Owner creates a 'viewer' role (server generates the share code!)
    res_role = client.post(
        "/api/v1/vault/roles",
        headers=owner_headers,
        json={"label": "Mom Phone Read-Only", "role": "viewer", "allowed_member_id": "mom"},
    )
    assert res_role.status_code == 200
    viewer_code = res_role.json()["role_info"]["generated_share_code"]
    assert len(viewer_code) >= 16

    viewer_headers = {"X-Invite-Code": viewer_code}

    # Viewer is blocked from asking questions about 'dad' (P1 #7)
    res_ask_dad = client.post(
        "/api/v1/ask-question",
        headers=viewer_headers,
        json={"question": "What is my hemoglobin?", "member_id": "dad"},
    )
    assert res_ask_dad.status_code == 403


def test_brute_force_invite_code_lockout(client):
    """P0 #1: 5 wrong invite codes must trigger a 429 lockout on the 6th attempt."""
    _FAILED_ATTEMPTS.clear()
    for _ in range(5):
        r = client.get("/api/v1/auth/me", headers={"X-Invite-Code": "WRONG-GUESS-CODE"})
        assert r.status_code == 401

    r_locked = client.get("/api/v1/auth/me", headers={"X-Invite-Code": "WRONG-GUESS-CODE"})
    assert r_locked.status_code == 429
    _FAILED_ATTEMPTS.clear()