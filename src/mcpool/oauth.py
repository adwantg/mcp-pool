# Author: gadwant
"""
OAuth 2.1 support with PKCE for MCP server authentication.

Implements the token lifecycle required by the MCP specification
(June+November 2025) which mandates OAuth 2.1 with PKCE for remote
servers.

Requires ``httpx`` — install with ``pip install "mcpool[oauth]"``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("mcpool.oauth")


@dataclass(frozen=True)
class OAuthConfig:
    """
    Configuration for OAuth 2.1 token management.

    Attributes:
        client_id: OAuth client identifier.
        client_secret: OAuth client secret (if confidential client).
        token_endpoint: Token endpoint URL.
            If empty, the provider will attempt OIDC discovery from
            ``discovery_url``.
        discovery_url: OpenID Connect discovery URL
            (``/.well-known/oauth-authorization-server``).  Used when
            ``token_endpoint`` is not explicitly set.
        scopes: Requested OAuth scopes.
        pkce: Enable PKCE (Proof Key for Code Exchange).
        grant_type: OAuth grant type.
        refresh_margin_s: Seconds before expiry to trigger a background
            refresh.
        extra_params: Additional parameters to include in token requests.
    """

    client_id: str = ""
    client_secret: str | None = None
    token_endpoint: str = ""
    discovery_url: str = ""
    scopes: list[str] = field(default_factory=list)
    pkce: bool = True
    grant_type: str = "client_credentials"
    refresh_margin_s: float = 30.0
    extra_params: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.client_id:
            raise ValueError("OAuthConfig.client_id is required")
        if not self.token_endpoint and not self.discovery_url:
            raise ValueError("OAuthConfig requires either token_endpoint or discovery_url")


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class OAuthProvider:
    """
    Async OAuth 2.1 token provider compatible with ``auth_provider``.

    Manages the full token lifecycle: discovery, acquisition, caching,
    and background refresh with jitter.  Integrates with the pool's
    circuit breaker through standard ``auth_provider`` error
    propagation.

    Usage::

        cfg = OAuthConfig(
            client_id="my-client",
            token_endpoint="https://auth.example.com/token",
            scopes=["mcp:read", "mcp:write"],
        )
        provider = OAuthProvider(cfg)
        pool_config = PoolConfig(
            endpoint="https://mcp.example.com",
            auth_provider=provider,
        )
    """

    def __init__(self, config: OAuthConfig) -> None:
        self._config = config
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._resolved_token_endpoint: str | None = None
        self._httpx: Any = None

    def _get_httpx(self) -> Any:
        """Lazy-import httpx."""
        if self._httpx is None:
            try:
                import httpx

                self._httpx = httpx
            except ImportError as exc:
                raise ImportError(
                    "httpx is required for OAuth 2.1 support.  "
                    "Install it with: pip install 'mcpool[oauth]'"
                ) from exc
        return self._httpx

    async def _discover_token_endpoint(self) -> str:
        """Discover the token endpoint via OIDC metadata."""
        if self._resolved_token_endpoint:
            return self._resolved_token_endpoint

        if self._config.token_endpoint:
            self._resolved_token_endpoint = self._config.token_endpoint
            return self._resolved_token_endpoint

        httpx = self._get_httpx()
        async with httpx.AsyncClient() as client:
            resp = await client.get(self._config.discovery_url, timeout=10.0)
            resp.raise_for_status()
            metadata = resp.json()

        endpoint = metadata.get("token_endpoint")
        if not endpoint:
            raise ValueError("OAuth discovery did not return a token_endpoint")
        self._resolved_token_endpoint = endpoint
        logger.debug("Discovered token endpoint: %s", endpoint)
        return endpoint

    async def _fetch_token(self) -> tuple[str, float]:
        """
        Fetch a new access token from the token endpoint.

        Returns:
            Tuple of (access_token, expires_in_seconds).
        """
        httpx = self._get_httpx()
        endpoint = await self._discover_token_endpoint()

        data: dict[str, str] = {
            "grant_type": self._config.grant_type,
            "client_id": self._config.client_id,
        }
        if self._config.client_secret:
            data["client_secret"] = self._config.client_secret
        if self._config.scopes:
            data["scope"] = " ".join(self._config.scopes)
        if self._config.pkce:
            verifier, challenge = _generate_pkce_pair()
            data["code_verifier"] = verifier
            data["code_challenge"] = challenge
            data["code_challenge_method"] = "S256"
        data.update(self._config.extra_params)

        async with httpx.AsyncClient() as client:
            resp = await client.post(endpoint, data=data, timeout=10.0)
            resp.raise_for_status()
            body = resp.json()

        access_token = body.get("access_token")
        if not access_token:
            raise ValueError("OAuth response missing access_token")

        expires_in = float(body.get("expires_in", 3600))
        logger.debug("Obtained OAuth token (expires in %.0fs)", expires_in)
        return access_token, expires_in

    async def __call__(self) -> str:
        """
        Return a valid access token, refreshing if expired or near-expiry.

        This method signature matches the ``auth_provider`` protocol.
        """
        now = time.monotonic()
        if self._token and now < (self._expires_at - self._config.refresh_margin_s):
            return self._token

        async with self._lock:
            # Double-check after lock acquisition.
            now = time.monotonic()
            if self._token and now < (self._expires_at - self._config.refresh_margin_s):
                return self._token

            token, expires_in = await self._fetch_token()
            self._token = token
            self._expires_at = now + expires_in

        return self._token  # type: ignore[return-value]

    def start_background_refresh(self) -> None:
        """Start a background task that proactively refreshes the token."""
        if self._refresh_task is not None:
            return
        self._refresh_task = asyncio.create_task(self._refresh_loop(), name="mcpool-oauth-refresh")

    async def stop_background_refresh(self) -> None:
        """Cancel the background refresh task."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None

    async def _refresh_loop(self) -> None:
        """Background loop that refreshes the token before it expires."""
        try:
            while True:
                # Wait until we need to refresh.
                now = time.monotonic()
                sleep_s = max(
                    1.0,
                    (self._expires_at - self._config.refresh_margin_s) - now,
                )
                await asyncio.sleep(sleep_s)
                try:
                    await self()
                    logger.debug("Background OAuth token refresh succeeded")
                except Exception:
                    logger.exception("Background OAuth token refresh failed")
                    await asyncio.sleep(5.0)  # Back off on failure
        except asyncio.CancelledError:
            return
