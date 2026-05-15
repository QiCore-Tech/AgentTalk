"""Authentication module supporting both local and Casdoor OAuth."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AuthContext:
    """Authentication context for a request."""
    user_id: str
    username: str
    display_name: str
    email: str = ""
    avatar: str = ""
    auth_method: str = ""  # "local" | "casdoor"


class AuthManager:
    """Manages authentication for AgentTalk Hub."""

    def __init__(
        self,
        *,
        token: str,
        auth_mode: str = "token",
        casdoor_endpoint: str = "",
        casdoor_client_id: str = "",
        casdoor_client_secret: str = "",
        casdoor_app_name: str = "",
        casdoor_org_name: str = "",
        jwt_secret: str = "",
        jwt_expiry_hours: int = 24,
    ):
        self._token = token
        self.auth_mode = auth_mode
        # Casdoor settings
        self.casdoor_endpoint = casdoor_endpoint.rstrip("/")
        self.casdoor_client_id = casdoor_client_id
        self.casdoor_client_secret = casdoor_client_secret
        self.casdoor_app_name = casdoor_app_name
        self.casdoor_org_name = casdoor_org_name
        # Local auth settings
        self.jwt_secret = jwt_secret or secrets.token_urlsafe(32)
        self.jwt_expiry_hours = jwt_expiry_hours
        # In-memory store for pending machine registrations
        self._pending_registrations: dict[str, dict] = {}

    def verify_bearer(self, authorization: str | None) -> AuthContext | None:
        """Verify a bearer token and return auth context.

        Supports:
        1. Hub admin token (legacy)
        2. Local JWT token
        3. Casdoor access token
        """
        if not authorization:
            return None

        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        token = parts[1]

        # 1. Check hub admin token (legacy)
        if token == self._token:
            return AuthContext(
                user_id="admin",
                username="admin",
                display_name="Administrator",
                auth_method="token",
            )

        # 2. Check if it's a local JWT
        if self.auth_mode in ("local", "both"):
            try:
                payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
                return AuthContext(
                    user_id=payload["sub"],
                    username=payload.get("username", payload["sub"]),
                    display_name=payload.get("display_name", payload["sub"]),
                    email=payload.get("email", ""),
                    auth_method="local",
                )
            except jwt.InvalidTokenError:
                pass

        # 3. Check if it's a Casdoor token
        if self.auth_mode in ("casdoor", "both"):
            try:
                user_info = self._verify_casdoor_token(token)
                if user_info:
                    return AuthContext(
                        user_id=user_info.get("id", user_info.get("name", "")),
                        username=user_info.get("name", ""),
                        display_name=user_info.get("displayName", user_info.get("name", "")),
                        email=user_info.get("email", ""),
                        avatar=user_info.get("avatar", ""),
                        auth_method="casdoor",
                    )
            except Exception:
                pass

        return None

    def _verify_casdoor_token(self, token: str) -> dict | None:
        """Verify a Casdoor access token and return user info."""
        if not self.casdoor_endpoint:
            return None

        # Casdoor introspection endpoint
        url = f"{self.casdoor_endpoint}/api/login/oauth/access_token"
        try:
            response = httpx.post(
                url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.casdoor_client_id,
                    "client_secret": self.casdoor_client_secret,
                    "code": token,
                },
                timeout=10,
            )
            if response.status_code != 200:
                return None
            data = response.json()
            if data.get("status") != "ok":
                return None
            return data.get("data")
        except Exception:
            return None

    def create_local_jwt(self, user_id: str, username: str, display_name: str = "") -> str:
        """Create a local JWT token for a user."""
        now = int(time.time())
        payload = {
            "sub": user_id,
            "username": username,
            "display_name": display_name or username,
            "iat": now,
            "exp": now + self.jwt_expiry_hours * 3600,
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def get_casdoor_login_url(self, redirect_uri: str, state: str = "") -> str:
        """Get Casdoor OAuth login URL."""
        if not self.casdoor_endpoint:
            raise RuntimeError("Casdoor endpoint not configured")

        params = {
            "client_id": self.casdoor_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "read",
            "state": state or secrets.token_urlsafe(16),
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.casdoor_endpoint}/login/oauth/authorize?{query}"

    def exchange_casdoor_code(self, code: str, redirect_uri: str = "") -> dict:
        """Exchange Casdoor authorization code for access token."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not self.casdoor_endpoint:
            raise RuntimeError("Casdoor endpoint not configured")

        url = f"{self.casdoor_endpoint}/api/login/oauth/access_token"
        data = {
            "grant_type": "authorization_code",
            "client_id": self.casdoor_client_id,
            "client_secret": self.casdoor_client_secret,
            "code": code,
        }
        if redirect_uri:
            data["redirect_uri"] = redirect_uri
            
        logger.info(f"Exchanging code with redirect_uri: {redirect_uri}")
        
        response = httpx.post(
            url,
            data=data,
            timeout=10,
        )
        
        try:
            result = response.json()
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid response from Casdoor: {response.text}")
        
        logger.info(f"Casdoor token response status={response.status_code}: {result}")
        
        # Check for standard OAuth error
        if "error" in result:
            error_desc = result.get("error_description", result["error"])
            raise HTTPException(status_code=400, detail=f"OAuth error: {error_desc}")
        
        # Check for Casdoor custom error format
        if result.get("status") == "error":
            error_msg = result.get("msg", "Casdoor authentication failed")
            logger.error(f"Casdoor authentication failed. Full response: {result}")
            logger.error(f"Request data: client_id={self.casdoor_client_id}, redirect_uri={redirect_uri}")
            raise HTTPException(status_code=400, detail=f"Casdoor error: {error_msg}")
        
        # Success - Casdoor returns standard OAuth format (access_token, id_token, etc.)
        return result

    def get_casdoor_user_info(self, access_token: str) -> dict:
        """Get user info from Casdoor using access token."""
        if not self.casdoor_endpoint:
            raise RuntimeError("Casdoor endpoint not configured")

        url = f"{self.casdoor_endpoint}/api/get-account"
        headers = {"Authorization": f"Bearer {access_token}"}
        response = httpx.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok":
            raise HTTPException(status_code=400, detail="Failed to get user info")
        return data.get("data", {})

    # Machine registration helpers
    def create_registration_token(self, relay_machine_id: str, host_name: str) -> str:
        """Create a pending machine registration token."""
        token = secrets.token_urlsafe(32)
        self._pending_registrations[token] = {
            "relay_machine_id": relay_machine_id,
            "host_name": host_name,
            "created_at": time.time(),
            "user_id": None,  # Will be filled after OAuth
        }
        return token

    def get_pending_registration(self, token: str) -> dict | None:
        """Get pending registration info."""
        return self._pending_registrations.get(token)

    def complete_registration(self, token: str, user_id: str) -> dict | None:
        """Complete a machine registration with user ID."""
        reg = self._pending_registrations.get(token)
        if reg is None:
            return None
        reg["user_id"] = user_id
        # Clean up old registrations
        now = time.time()
        expired = [
            t for t, r in self._pending_registrations.items()
            if now - r["created_at"] > 600  # 10 minutes
        ]
        for t in expired:
            self._pending_registrations.pop(t, None)
        return reg


def get_auth_context(request: Request) -> AuthContext | None:
    """FastAPI dependency to get auth context from request."""
    auth: AuthManager | None = getattr(request.app.state, "auth_manager", None)
    if auth is None:
        return None
    authorization = request.headers.get("authorization")
    return auth.verify_bearer(authorization)
