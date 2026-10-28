import os
import time
import logging
from typing import Optional, Dict, Any, List, Tuple
import httpx
from pydantic import BaseModel
from fastapi import Header, HTTPException, Depends
from supabase import create_client, Client

from .crypto import token_encryptor, TokenEncryptionError

logger = logging.getLogger(__name__)

class AuthUser(BaseModel):
    """Authenticated user model verified against Supabase Auth."""
    id: str
    email: Optional[str] = None
    user_metadata: Dict[str, Any] = {}
    role: str = "authenticated"

class SupabaseManager:
    """
    Manages Supabase client operations, token verification, and user-scoped data persistence.
    When Supabase credentials are not configured, gracefully falls back to local in-memory/guest mode.
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_service_role_key: Optional[str] = None,
        supabase_anon_key: Optional[str] = None
    ):
        self.url = (supabase_url or os.getenv("SUPABASE_URL", "")).strip().rstrip("/")
        self.service_role_key = (supabase_service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
        self.anon_key = (supabase_anon_key or os.getenv("SUPABASE_ANON_KEY", "")).strip()

        self._client: Optional[Client] = None
        self._token_cache: Dict[str, Tuple[AuthUser, float]] = {}  # token -> (AuthUser, expiry_time)

        if self.is_configured:
            try:
                self._client = create_client(self.url, self.service_role_key)
                logger.info(f"Supabase client initialized successfully for {self.url}")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                self._client = None
        else:
            logger.info("Supabase is not configured. Patchworks running in guest/demo mode.")

    @property
    def is_configured(self) -> bool:
        """True if server-side URL and Service Role Key are present."""
        return bool(self.url and self.service_role_key)

    @property
    def client(self) -> Optional[Client]:
        return self._client

    def verify_jwt(self, jwt_token: str) -> Optional[AuthUser]:
        """
        Verify a Supabase access token (JWT) authoritatively against Supabase Auth.
        Caches successfully verified tokens for up to 60 seconds to reduce latency.
        """
        if not jwt_token or not isinstance(jwt_token, str):
            return None

        # Check in-memory short-lived cache
        now = time.time()
        if jwt_token in self._token_cache:
            user, exp = self._token_cache[jwt_token]
            if exp > now:
                return user
            del self._token_cache[jwt_token]

        if not self.is_configured:
            # When Supabase is not configured in local testing, support synthetic mock tokens
            if jwt_token.startswith("mock_jwt_"):
                mock_user_id = jwt_token.replace("mock_jwt_", "")
                return AuthUser(id=mock_user_id, email=f"{mock_user_id}@test.local")
            return None

        # Query Supabase Auth API /auth/v1/user
        auth_url = f"{self.url}/auth/v1/user"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "apikey": self.anon_key or self.service_role_key
        }

        try:
            with httpx.Client(timeout=10.0) as http_client:
                resp = http_client.get(auth_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    user = AuthUser(
                        id=data.get("id"),
                        email=data.get("email"),
                        user_metadata=data.get("user_metadata", {}) or {},
                        role=data.get("role", "authenticated")
                    )
                    # Cache for 60 seconds or until token expires
                    self._token_cache[jwt_token] = (user, now + 60.0)
                    return user
                else:
                    logger.warning(f"Supabase JWT verification failed with status {resp.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error communicating with Supabase Auth endpoint: {e}")
            return None

    def verify_token(self, jwt_token: str) -> Optional[AuthUser]:
        """Alias for verify_jwt."""
        return self.verify_jwt(jwt_token)

    def get_user_from_auth_header(self, authorization: Optional[str]) -> Optional[AuthUser]:
        """Extract and verify user directly from Authorization header string."""
        token = extract_bearer_token(authorization)
        if not token:
            return None
        return self.verify_jwt(token)

    # -------------------------------------------------------------------------
    # User-Scoped GitHub Connection Storage (Explicit user_id constraint)
    # -------------------------------------------------------------------------

    def save_github_connection(
        self,
        user_id: str,
        github_user_id: Optional[str],
        github_login: str,
        encrypted_token: str,
        avatar_url: Optional[str] = None,
        html_url: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        auth_type: str = "oauth"
    ) -> bool:
        """
        Upsert a GitHub connection record strictly constrained to user_id.
        The token MUST already be encrypted at rest before calling this method.
        """
        if not self.is_configured or self._client is None:
            return False

        payload = {
            "user_id": user_id,
            "github_user_id": str(github_user_id) if github_user_id else None,
            "github_login": github_login,
            "encrypted_access_token": encrypted_token,
            "avatar_url": avatar_url,
            "html_url": html_url,
            "scopes": scopes or [],
            "auth_type": auth_type,
            "updated_at": "now()"
        }

        try:
            res = self._client.table("github_connections").upsert(payload, on_conflict="user_id").execute()
            return bool(res.data)
        except Exception as e:
            logger.error(f"Failed to save github_connection for user {user_id}: {e}")
            raise

    def get_github_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the GitHub connection record for the verified user_id.
        Returns None if not found or unconfigured.
        """
        if not self.is_configured or self._client is None:
            return None

        try:
            res = (
                self._client.table("github_connections")
                .select("*")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            return res.data if res else None
        except Exception as e:
            logger.error(f"Failed to query github_connection for user {user_id}: {e}")
            return None

    def delete_github_connection(self, user_id: str) -> bool:
        """
        Delete the GitHub connection record for the verified user_id.
        """
        if not self.is_configured or self._client is None:
            return False

        try:
            res = self._client.table("github_connections").delete().eq("user_id", user_id).execute()
            return bool(res.data)
        except Exception as e:
            logger.error(f"Failed to delete github_connection for user {user_id}: {e}")
            return False

    # -------------------------------------------------------------------------
    # User-Scoped Repair Sessions / History
    # -------------------------------------------------------------------------

    def save_repair_session(self, user_id: Optional[str], session_data: Dict[str, Any]) -> Optional[str]:
        """
        Persist a repair session record in Supabase.
        Returns the session UUID or None.
        """
        if not self.is_configured or self._client is None:
            return None

        record = {
            "user_id": user_id,
            "workspace_id": session_data.get("workspace_id"),
            "repo_url": session_data.get("repo_url", ""),
            "issue_description": session_data.get("issue_description", ""),
            "mode": session_data.get("mode", "targeted"),
            "status": session_data.get("status", "completed"),
            "diagnosis": session_data.get("diagnosis", {}),
            "findings": session_data.get("findings", []),
            "patch": session_data.get("patch"),
            "verification_status": session_data.get("verification_status", "UNVERIFIED"),
            "verification_details": session_data.get("verification_details", {}),
            "pr_url": session_data.get("pr_url"),
            "pr_number": session_data.get("pr_number"),
            "branch": session_data.get("branch")
        }

        try:
            res = self._client.table("repair_sessions").insert(record).execute()
            if res.data and len(res.data) > 0:
                return res.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"Failed to save repair_session: {e}")
            return None

    def list_repair_sessions(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        List repair sessions strictly scoped to user_id, ordered by creation date descending.
        """
        if not self.is_configured or self._client is None:
            return []

        try:
            res = (
                self._client.table("repair_sessions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error(f"Failed to list repair_sessions for user {user_id}: {e}")
            return []

    def delete_repair_session(self, user_id: str, session_id: str) -> bool:
        """
        Delete a single repair session strictly constrained to user_id.
        """
        if not self.is_configured or self._client is None:
            return False

        try:
            res = (
                self._client.table("repair_sessions")
                .delete()
                .eq("id", session_id)
                .eq("user_id", user_id)
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.error(f"Failed to delete repair_session {session_id} for user {user_id}: {e}")
            return False

# Global instance
supabase_manager = SupabaseManager()

# -----------------------------------------------------------------------------
# FastAPI Dependencies
# -----------------------------------------------------------------------------

def extract_bearer_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Helper to extract bearer token from Authorization header."""
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None

def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[AuthUser]:
    """
    FastAPI dependency for endpoints that allow guest access.
    Returns AuthUser if valid Bearer token provided, or None for anonymous guests.
    """
    token = extract_bearer_token(authorization)
    if not token:
        return None
    return supabase_manager.verify_jwt(token)

def get_current_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """
    FastAPI dependency for endpoints that strictly require an authenticated user.
    Raises HTTP 401 if token is missing, expired, or invalid.
    """
    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please sign in with your account."
        )

    user = supabase_manager.verify_jwt(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid, expired, or unrecognized authentication token."
        )

    return user
