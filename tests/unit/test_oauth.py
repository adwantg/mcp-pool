# Author: gadwant
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpool.oauth import OAuthConfig, OAuthProvider, _generate_pkce_pair


class TestOAuthConfig:
    def test_requires_client_id(self):
        with pytest.raises(ValueError, match="client_id is required"):
            OAuthConfig(token_endpoint="https://auth.example.com/token")

    def test_requires_endpoint_or_discovery(self):
        with pytest.raises(ValueError, match="token_endpoint or discovery_url"):
            OAuthConfig(client_id="my-client")

    def test_valid_config(self):
        cfg = OAuthConfig(
            client_id="my-client",
            token_endpoint="https://auth.example.com/token",
            scopes=["mcp:read"],
        )
        assert cfg.client_id == "my-client"
        assert cfg.pkce is True


class TestPKCE:
    def test_generate_pkce_pair(self):
        verifier, challenge = _generate_pkce_pair()
        assert len(verifier) > 20
        assert len(challenge) > 20
        assert verifier != challenge


class TestOAuthProvider:
    def test_import_error_when_no_httpx(self):
        cfg = OAuthConfig(
            client_id="test",
            token_endpoint="https://auth.example.com/token",
        )
        provider = OAuthProvider(cfg)
        with (
            patch.dict("sys.modules", {"httpx": None}),
            pytest.raises(ImportError, match="httpx is required"),
        ):
            provider._get_httpx()

    @pytest.mark.asyncio
    async def test_fetch_token(self):
        cfg = OAuthConfig(
            client_id="test-client",
            client_secret="secret",
            token_endpoint="https://auth.example.com/token",
            scopes=["mcp:read"],
            pkce=False,
        )
        provider = OAuthProvider(cfg)

        mock_httpx = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "tok-abc123",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx.AsyncClient.return_value = mock_client
        provider._httpx = mock_httpx

        token, expires_in = await provider._fetch_token()
        assert token == "tok-abc123"
        assert expires_in == 3600.0

    @pytest.mark.asyncio
    async def test_call_returns_cached_token(self):
        cfg = OAuthConfig(
            client_id="test",
            token_endpoint="https://auth.example.com/token",
        )
        provider = OAuthProvider(cfg)
        provider._token = "cached-token"
        provider._expires_at = time.monotonic() + 3600

        result = await provider()
        assert result == "cached-token"

    @pytest.mark.asyncio
    async def test_call_refreshes_expired_token(self):
        cfg = OAuthConfig(
            client_id="test",
            token_endpoint="https://auth.example.com/token",
            refresh_margin_s=10.0,
        )
        provider = OAuthProvider(cfg)
        provider._token = "old-token"
        provider._expires_at = time.monotonic() - 1  # expired

        mock_httpx = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx.AsyncClient.return_value = mock_client
        provider._httpx = mock_httpx

        result = await provider()
        assert result == "new-token"

    @pytest.mark.asyncio
    async def test_discovery(self):
        cfg = OAuthConfig(
            client_id="test",
            discovery_url="https://auth.example.com/.well-known/oauth-authorization-server",
        )
        provider = OAuthProvider(cfg)

        mock_httpx = MagicMock()

        # Discovery response
        mock_disc_response = MagicMock()
        mock_disc_response.json.return_value = {
            "token_endpoint": "https://auth.example.com/oauth/token"
        }
        mock_disc_response.raise_for_status = MagicMock()

        mock_disc_client = AsyncMock()
        mock_disc_client.get = AsyncMock(return_value=mock_disc_response)
        mock_disc_client.__aenter__ = AsyncMock(return_value=mock_disc_client)
        mock_disc_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx.AsyncClient.return_value = mock_disc_client
        provider._httpx = mock_httpx

        endpoint = await provider._discover_token_endpoint()
        assert endpoint == "https://auth.example.com/oauth/token"

    @pytest.mark.asyncio
    async def test_discovery_missing_endpoint(self):
        cfg = OAuthConfig(
            client_id="test",
            discovery_url="https://auth.example.com/.well-known",
        )
        provider = OAuthProvider(cfg)

        mock_httpx = MagicMock()
        mock_disc_response = MagicMock()
        mock_disc_response.json.return_value = {}
        mock_disc_response.raise_for_status = MagicMock()

        mock_disc_client = AsyncMock()
        mock_disc_client.get = AsyncMock(return_value=mock_disc_response)
        mock_disc_client.__aenter__ = AsyncMock(return_value=mock_disc_client)
        mock_disc_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx.AsyncClient.return_value = mock_disc_client
        provider._httpx = mock_httpx

        with pytest.raises(ValueError, match="did not return a token_endpoint"):
            await provider._discover_token_endpoint()

    @pytest.mark.asyncio
    async def test_missing_access_token_raises(self):
        cfg = OAuthConfig(
            client_id="test",
            token_endpoint="https://auth.example.com/token",
            pkce=False,
        )
        provider = OAuthProvider(cfg)

        mock_httpx = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "invalid_grant"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx.AsyncClient.return_value = mock_client
        provider._httpx = mock_httpx

        with pytest.raises(ValueError, match="missing access_token"):
            await provider._fetch_token()

    @pytest.mark.asyncio
    async def test_background_refresh_lifecycle(self):
        cfg = OAuthConfig(
            client_id="test",
            token_endpoint="https://auth.example.com/token",
        )
        provider = OAuthProvider(cfg)

        provider.start_background_refresh()
        assert provider._refresh_task is not None

        await provider.stop_background_refresh()
        assert provider._refresh_task is None

    @pytest.mark.asyncio
    async def test_start_background_refresh_idempotent(self):
        cfg = OAuthConfig(
            client_id="test",
            token_endpoint="https://auth.example.com/token",
        )
        provider = OAuthProvider(cfg)

        provider.start_background_refresh()
        first_task = provider._refresh_task

        provider.start_background_refresh()
        assert provider._refresh_task is first_task

        await provider.stop_background_refresh()
