import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.crypto import TokenEncryptor, TokenEncryptionError
from backend.app.auth import AuthUser, SupabaseManager, get_optional_user, get_current_user
from backend.app.main import app

client = TestClient(app)


# =====================================================================
# 1. Token Encryption Tests (AES-128-CBC + HMAC-SHA256 via Fernet)
# =====================================================================

class TestTokenEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        key = TokenEncryptor.generate_key()
        encryptor = TokenEncryptor(key_or_keys=key)
        secret_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        
        ciphertext = encryptor.encrypt(secret_token)
        assert ciphertext != secret_token
        assert "ghp_" not in ciphertext
        
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == secret_token

    def test_tampered_ciphertext_fails(self):
        key = TokenEncryptor.generate_key()
        encryptor = TokenEncryptor(key_or_keys=key)
        ciphertext = encryptor.encrypt("ghp_secret_token")
        
        # Tamper with the ciphertext
        tampered = ciphertext[:-4] + "AAAA"
        with pytest.raises(TokenEncryptionError, match="Invalid or corrupted ciphertext"):
            encryptor.decrypt(tampered)

    def test_multi_fernet_key_rotation(self):
        # Generate two keys: old_key and new_key
        old_key = TokenEncryptor.generate_key()
        new_key = TokenEncryptor.generate_key()
        
        # Encrypt with old_key
        old_encryptor = TokenEncryptor(key_or_keys=old_key)
        original_token = "ghp_rotation_test_token_9999"
        old_ciphertext = old_encryptor.encrypt(original_token)
        
        # Create rotating encryptor with new_key as primary, old_key as fallback
        rotating_encryptor = TokenEncryptor(key_or_keys=f"{new_key},{old_key}")
        
        # Should decrypt old ciphertext using fallback key
        decrypted = rotating_encryptor.decrypt(old_ciphertext)
        assert decrypted == original_token
        
        # Rotate ciphertext so it is re-encrypted with primary (new_key)
        rotated_ciphertext, was_changed = rotating_encryptor.rotate(old_ciphertext)
        assert was_changed is True
        assert rotated_ciphertext != old_ciphertext
        
        # An encryptor that only has new_key can decrypt the rotated ciphertext
        new_encryptor = TokenEncryptor(key_or_keys=new_key)
        assert new_encryptor.decrypt(rotated_ciphertext) == original_token
        
        # But an encryptor with only old_key cannot decrypt rotated_ciphertext
        with pytest.raises(TokenEncryptionError):
            old_encryptor.decrypt(rotated_ciphertext)

    def test_key_cannot_match_service_role_key(self):
        reused_secret = TokenEncryptor.generate_key()
        with pytest.raises(ValueError, match="cannot match SUPABASE_SERVICE_ROLE_KEY"):
            TokenEncryptor(key_or_keys=reused_secret, service_role_key=reused_secret)

    def test_empty_string_rejection(self):
        encryptor = TokenEncryptor(key_or_keys=TokenEncryptor.generate_key())
        with pytest.raises(TokenEncryptionError):
            encryptor.encrypt("")
        with pytest.raises(TokenEncryptionError):
            encryptor.decrypt("")


# =====================================================================
# 2. Authentication Dependency & Token Verification Tests
# =====================================================================

class TestAuthDependencies:
    def test_get_optional_user_no_header(self):
        mgr = SupabaseManager()
        # No header
        user = mgr.get_user_from_auth_header(None)
        assert user is None

    def test_get_optional_user_invalid_bearer(self):
        mgr = SupabaseManager()
        # Invalid format
        assert mgr.get_user_from_auth_header("Basic 12345") is None

    @patch("httpx.Client.get")
    def test_get_user_valid_jwt(self, mock_get):
        # Mock Supabase user verification response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "user-uuid-1111",
            "email": "dev1@patchworks.test",
            "app_metadata": {},
            "user_metadata": {"avatar_url": "https://avatar.test/1.png"}
        }
        mock_get.return_value = mock_resp

        mgr = SupabaseManager(
            supabase_url="https://test.supabase.co",
            supabase_service_role_key="test-service-key",
            supabase_anon_key="anon-key"
        )
        user = mgr.verify_jwt("valid_jwt_token_abc")
        
        assert user is not None
        assert user.id == "user-uuid-1111"
        assert user.email == "dev1@patchworks.test"
        assert user.user_metadata.get("avatar_url") == "https://avatar.test/1.png"

    @patch("httpx.Client.get")
    def test_get_user_cached_token(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "cached-user-2222",
            "email": "cached@patchworks.test",
            "app_metadata": {},
            "user_metadata": {}
        }
        mock_get.return_value = mock_resp

        mgr = SupabaseManager(
            supabase_url="https://test.supabase.co",
            supabase_service_role_key="test-service-key",
            supabase_anon_key="anon-key"
        )
        user1 = mgr.verify_jwt("token_cache_test")
        user2 = mgr.verify_jwt("token_cache_test")
        
        assert user1.id == user2.id == "cached-user-2222"
        # Only 1 network request because of the TTL cache
        assert mock_get.call_count == 1


# =====================================================================
# 3. User Isolation & Endpoint Authorization Tests
# =====================================================================

class TestUserIsolationAndPersistence:
    @pytest.fixture(autouse=True)
    def setup_mock_db(self):
        """Simulate an isolated mock DB storage inside supabase_manager."""
        from backend.app import main
        
        self.mock_connections = {}  # user_id -> record
        self.mock_sessions = {}     # (user_id, session_id) -> record

        # Mock supabase_manager methods
        orig_save_conn = main.supabase_manager.save_github_connection
        orig_get_conn = main.supabase_manager.get_github_connection
        orig_del_conn = main.supabase_manager.delete_github_connection
        orig_save_sess = main.supabase_manager.save_repair_session
        orig_list_sess = main.supabase_manager.list_repair_sessions
        orig_del_sess = main.supabase_manager.delete_repair_session
        orig_verify_jwt = main.supabase_manager.verify_jwt

        def mock_verify_jwt(token):
            if token == "user_a_token":
                return AuthUser(id="user_a_uuid", email="alice@test.com")
            elif token == "user_b_token":
                return AuthUser(id="user_b_uuid", email="bob@test.com")
            return None

        def mock_save_connection(user_id, github_user_id, github_login, encrypted_token, **kwargs):
            self.mock_connections[user_id] = {
                "user_id": user_id,
                "github_user_id": github_user_id,
                "github_login": github_login,
                "encrypted_access_token": encrypted_token,
                "avatar_url": kwargs.get("avatar_url"),
                "html_url": kwargs.get("html_url"),
                "scopes": kwargs.get("scopes", []),
                "auth_type": kwargs.get("auth_type", "pat"),
            }
            return True

        def mock_get_connection(user_id):
            return self.mock_connections.get(user_id)

        def mock_delete_connection(user_id):
            if user_id in self.mock_connections:
                del self.mock_connections[user_id]
                return True
            return False

        def mock_save_repair_session(user_id, session_data):
            sess_id = f"sess_{len(self.mock_sessions) + 1}"
            session_data["id"] = sess_id
            session_data["user_id"] = user_id
            self.mock_sessions[(user_id, sess_id)] = session_data
            return sess_id

        def mock_list_repair_sessions(user_id, limit=20):
            return [
                v for (u_id, s_id), v in self.mock_sessions.items()
                if u_id == user_id
            ]

        def mock_delete_repair_session(user_id, session_id):
            key = (user_id, session_id)
            if key in self.mock_sessions:
                del self.mock_sessions[key]
                return True
            return False

        orig_url = main.supabase_manager.url
        orig_key = main.supabase_manager.service_role_key
        main.supabase_manager.url = "https://mock.supabase.co"
        main.supabase_manager.service_role_key = "mock-service-role-key"

        main.supabase_manager.verify_jwt = mock_verify_jwt
        main.supabase_manager.verify_token = mock_verify_jwt
        main.supabase_manager.save_github_connection = mock_save_connection
        main.supabase_manager.get_github_connection = mock_get_connection
        main.supabase_manager.delete_github_connection = mock_delete_connection
        main.supabase_manager.save_repair_session = mock_save_repair_session
        main.supabase_manager.list_repair_sessions = mock_list_repair_sessions
        main.supabase_manager.delete_repair_session = mock_delete_repair_session

        yield

        # Restore original methods and config
        main.supabase_manager.url = orig_url
        main.supabase_manager.service_role_key = orig_key
        main.supabase_manager.save_github_connection = orig_save_conn
        main.supabase_manager.get_github_connection = orig_get_conn
        main.supabase_manager.delete_github_connection = orig_del_conn
        main.supabase_manager.save_repair_session = orig_save_sess
        main.supabase_manager.list_repair_sessions = orig_list_sess
        main.supabase_manager.delete_repair_session = orig_del_sess
        main.supabase_manager.verify_jwt = orig_verify_jwt
        main.supabase_manager.verify_token = orig_verify_jwt

    @patch("backend.app.github_service.GitHubService.verify_token")
    def test_github_connection_isolation_between_users(self, mock_gh_verify):
        # Mock GitHub user verification
        mock_gh_verify.return_value = {
            "valid": True,
            "login": "alice_github",
            "id": 12345,
            "avatar_url": "https://github.com/alice.png",
            "html_url": "https://github.com/alice_github",
            "scopes": ["repo"]
        }

        # 1. User A connects GitHub PAT
        res = client.post(
            "/api/github/connect",
            json={"token": "ghp_alice_secret_token_123"},
            headers={"Authorization": "Bearer user_a_token"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["connected"] is True
        assert data["user"]["login"] == "alice_github"
        # CRITICAL SECURITY CHECK: Raw or encrypted token is NEVER returned
        assert "token" not in data
        assert "encrypted_access_token" not in data

        # 2. User A checks their GitHub status
        res_a = client.get("/api/github/status", headers={"Authorization": "Bearer user_a_token"})
        assert res_a.status_code == 200
        assert res_a.json()["connected"] is True
        assert res_a.json()["user"]["login"] == "alice_github"

        # 3. User B checks their GitHub status -> MUST BE DISCONNECTED
        res_b = client.get("/api/github/status", headers={"Authorization": "Bearer user_b_token"})
        assert res_b.status_code == 200
        assert res_b.json()["connected"] is False
        assert res_b.json()["user"] is None

        # 4. User A disconnects GitHub -> User A is now disconnected
        res_disc = client.post("/api/github/disconnect", headers={"Authorization": "Bearer user_a_token"})
        assert res_disc.status_code == 200
        res_a_after = client.get("/api/github/status", headers={"Authorization": "Bearer user_a_token"})
        assert res_a_after.json()["connected"] is False

    def test_repair_history_isolation(self):
        # 1. Unauthenticated request to /api/history returns 401
        res_unauth = client.get("/api/history")
        assert res_unauth.status_code == 401

        # 2. User A saves a session
        res_save_a = client.post(
            "/api/history",
            json={
                "repo_url": "https://github.com/alice/demo-repo",
                "issue_description": "Fix memory leak in buffer",
                "mode": "targeted",
                "status": "completed",
                "patch": "--- a/buf.py\n+++ b/buf.py\n@@ -1 +1 @@\n-x\n+y"
            },
            headers={"Authorization": "Bearer user_a_token"}
        )
        assert res_save_a.status_code == 200
        sess_a_id = res_save_a.json()["session_id"]

        # 3. User A lists history -> sees 1 session
        res_list_a = client.get("/api/history", headers={"Authorization": "Bearer user_a_token"})
        assert res_list_a.status_code == 200
        sessions_a = res_list_a.json()["sessions"]
        assert len(sessions_a) == 1
        assert sessions_a[0]["repo_url"] == "https://github.com/alice/demo-repo"

        # 4. User B lists history -> sees 0 sessions (User B cannot see User A's sessions)
        res_list_b = client.get("/api/history", headers={"Authorization": "Bearer user_b_token"})
        assert res_list_b.status_code == 200
        assert len(res_list_b.json()["sessions"]) == 0

        # 5. User B attempts to delete User A's session -> denied (404/denied)
        res_del_b = client.delete(f"/api/history/{sess_a_id}", headers={"Authorization": "Bearer user_b_token"})
        assert res_del_b.status_code == 404

        # 6. User A deletes their session -> succeeds
        res_del_a = client.delete(f"/api/history/{sess_a_id}", headers={"Authorization": "Bearer user_a_token"})
        assert res_del_a.status_code == 200
        assert len(client.get("/api/history", headers={"Authorization": "Bearer user_a_token"}).json()["sessions"]) == 0

    def test_authenticated_user_never_inherits_guest_session_token(self):
        from backend.app import main
        # Set an in-memory session token on github_service (e.g. from an earlier guest session)
        main.github_service.set_session_token("ghp_guest_temporary_token_9999")
        try:
            # User B (authenticated, but has not connected GitHub) calls resolve_github_token
            user_b = AuthUser(id="user_b_uuid", email="bob@test.com")
            resolved = main.resolve_github_token(user=user_b)
            # MUST be None — User B must NEVER inherit the in-memory guest token!
            assert resolved is None

            # User B requests /api/github/repos -> MUST fail with 401
            res = client.get("/api/github/repos", headers={"Authorization": "Bearer user_b_token"})
            assert res.status_code == 401
        finally:
            main.github_service.set_session_token(None)

    def test_workspace_isolation_between_users(self):
        # 1. User A creates a benchmark workspace
        res_create = client.post(
            "/api/benchmark/workspace",
            json={"fixture": "simple_bug"},
            headers={"Authorization": "Bearer user_a_token"}
        )
        assert res_create.status_code == 200
        ws_id = res_create.json()["workspace_id"]

        try:
            # 2. User B tries to inspect User A's workspace -> 403 Forbidden
            res_inspect_b = client.post(
                "/api/inspect",
                json={"workspace_id": ws_id},
                headers={"Authorization": "Bearer user_b_token"}
            )
            assert res_inspect_b.status_code == 403
            assert "belongs to another user" in res_inspect_b.json()["detail"]

            # 3. User B tries to rollback User A's workspace -> 403 Forbidden
            res_rollback_b = client.post(
                "/api/rollback",
                json={"workspace_id": ws_id},
                headers={"Authorization": "Bearer user_b_token"}
            )
            assert res_rollback_b.status_code == 403

            # 4. Anonymous guest tries to delete User A's workspace -> 403 Forbidden
            res_del_guest = client.delete(f"/api/workspace/{ws_id}")
            assert res_del_guest.status_code == 403

            # 5. User B tries to delete User A's workspace -> 403 Forbidden
            res_del_b = client.delete(f"/api/workspace/{ws_id}", headers={"Authorization": "Bearer user_b_token"})
            assert res_del_b.status_code == 403

            # 6. User A inspects their own workspace -> 200 OK
            res_inspect_a = client.post(
                "/api/inspect",
                json={"workspace_id": ws_id},
                headers={"Authorization": "Bearer user_a_token"}
            )
            assert res_inspect_a.status_code == 200

            # 7. User A deletes their own workspace -> 200 OK
            res_del_a = client.delete(f"/api/workspace/{ws_id}", headers={"Authorization": "Bearer user_a_token"})
            assert res_del_a.status_code == 200
        finally:
            # Cleanup if not deleted
            from backend.app.main import workspace_manager
            workspace_manager.cleanup_workspace(ws_id)


# =====================================================================
# 4. Demo Mode Unauthenticated Compatibility Tests
# =====================================================================

class TestDemoModeCompatibility:
    def test_health_indicates_supabase_status(self):
        res = client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "supabase_configured" in data

    def test_guest_github_status_safe(self):
        res = client.get("/api/github/status")
        assert res.status_code == 200
        data = res.json()
        assert "connected" in data
        assert "configured" in data
