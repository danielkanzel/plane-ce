# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from plane.authentication.adapter.error import AuthenticationException
from plane.authentication.provider.oauth.oidc import OIDCOAuthProvider

ISSUER = "https://authentik.example.com/application/o/plane"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize/",
    "token_endpoint": f"{ISSUER}/token/",
    "userinfo_endpoint": f"{ISSUER}/userinfo/",
    "jwks_uri": f"{ISSUER}/jwks/",
    "id_token_signing_alg_values_supported": ["RS256"],
}


def _request():
    request = MagicMock()
    request.is_secure.return_value = True
    request.get_host.return_value = "plane.example.com"
    return request


def _config(*values):
    return patch(
        "plane.authentication.provider.oauth.oidc.get_configuration_value",
        return_value=values,
    )


@pytest.mark.unit
class TestOIDCOAuthProvider:
    def test_missing_configuration(self):
        with _config("0", None, None, None):
            with pytest.raises(AuthenticationException) as exc:
                OIDCOAuthProvider(request=_request(), state="state")
        assert exc.value.error_message == "OIDC_NOT_CONFIGURED"

    def test_rejects_issuer_without_scheme(self):
        with _config("1", "client", "secret", "authentik.example.com/application/o/plane"):
            with pytest.raises(AuthenticationException) as exc:
                OIDCOAuthProvider(request=_request(), state="state")
        assert exc.value.error_message == "OIDC_NOT_CONFIGURED"

    @patch("plane.authentication.provider.oauth.oidc.cache")
    @patch("plane.authentication.provider.oauth.oidc.requests.get")
    def test_authorization_url_uses_pkce(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_get.return_value = MagicMock(status_code=200, ok=True, json=lambda: DISCOVERY)
        mock_get.return_value.raise_for_status = MagicMock()

        with _config("1", "plane", "secret", f"{ISSUER}/"):
            provider = OIDCOAuthProvider(request=_request(), state="abc")

        auth_url = provider.get_auth_url()
        assert auth_url.startswith(f"{ISSUER}/authorize/")
        assert "code_challenge_method=S256" in auth_url
        assert "code_challenge=" in auth_url
        assert provider.code_verifier
        assert "https://plane.example.com/auth/oidc/callback/" in auth_url

    @patch("plane.authentication.provider.oauth.oidc.PyJWKClient")
    @patch("plane.authentication.provider.oauth.oidc.cache")
    @patch("plane.authentication.adapter.oauth.requests.get")
    @patch("plane.authentication.adapter.oauth.requests.post")
    def test_authentik_claims_create_user_data(self, mock_post, mock_get, mock_cache, mock_jwk_client):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        id_token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": "plane",
                "sub": "user-1",
                "exp": now + timedelta(minutes=5),
                "iat": now,
                "email": "ada@example.com",
                "email_verified": True,
            },
            private_key,
            algorithm="RS256",
        )
        mock_cache.get.return_value = DISCOVERY
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "access", "id_token": id_token, "expires_in": 300},
        )
        mock_post.return_value.raise_for_status = MagicMock()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "sub": "user-1",
                "email": "ada@example.com",
                "email_verified": True,
                "name": "Ada Lovelace",
                "preferred_username": "ada",
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        signing_key = MagicMock()
        signing_key.key = private_key.public_key()
        mock_jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key

        with _config("1", "plane", "secret", ISSUER):
            provider = OIDCOAuthProvider(request=_request(), code="code", code_verifier="verifier")
            provider.set_token_data()
            provider.set_user_data()

        assert provider.user_data["email"] == "ada@example.com"
        assert provider.user_data["user"]["provider_id"] == "user-1"
        assert provider.user_data["user"]["first_name"] == "Ada"
        assert provider.user_data["user"]["last_name"] == "Lovelace"
        token_request = mock_post.call_args.kwargs["data"]
        assert token_request["code_verifier"] == "verifier"

    @patch("plane.authentication.provider.oauth.oidc.PyJWKClient")
    @patch("plane.authentication.provider.oauth.oidc.cache")
    @patch("plane.authentication.adapter.oauth.requests.post")
    def test_rejects_unverified_email(self, mock_post, mock_cache, mock_jwk_client):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        id_token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": "plane",
                "sub": "user-1",
                "exp": now + timedelta(minutes=5),
                "email": "ada@example.com",
                "email_verified": False,
            },
            private_key,
            algorithm="RS256",
        )
        mock_cache.get.return_value = DISCOVERY
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "access", "id_token": id_token, "expires_in": 300},
        )
        mock_post.return_value.raise_for_status = MagicMock()
        signing_key = MagicMock()
        signing_key.key = private_key.public_key()
        mock_jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key

        with _config("1", "plane", "secret", ISSUER):
            provider = OIDCOAuthProvider(request=_request(), code="code", code_verifier="verifier")
            provider.set_token_data()
            with patch.object(
                provider,
                "get_user_response",
                return_value={"sub": "user-1", "email": "ada@example.com", "email_verified": False},
            ):
                with pytest.raises(AuthenticationException) as exc:
                    provider.set_user_data()
        assert exc.value.error_message == "OAUTH_PROVIDER_UNVERIFIED_EMAIL"

    def test_linked_subject_replaces_token_email(self):
        linked_user = MagicMock()
        linked_user.email = "owner@example.com"
        account = MagicMock()
        account.user = linked_user

        with _config("1", "plane", "secret", ISSUER):
            with patch("plane.authentication.provider.oauth.oidc.cache") as mock_cache:
                mock_cache.get.return_value = DISCOVERY
                provider = OIDCOAuthProvider(request=_request(), code="code", code_verifier="verifier")

        provider.user_data = {
            "email": "other@authentik.local",
            "user": {"provider_id": "akadmin", "email": "other@authentik.local"},
        }
        with patch("plane.authentication.provider.oauth.oidc.Account.objects") as accounts:
            accounts.filter.return_value.select_related.return_value.first.return_value = account
            with patch(
                "plane.authentication.adapter.oauth.OauthAdapter.complete_login_or_signup",
                return_value=linked_user,
            ) as complete:
                result = provider.complete_login_or_signup()

        assert result is linked_user
        assert provider.user_data["email"] == "owner@example.com"
        assert provider.user_data["user"]["email"] == "owner@example.com"
        accounts.filter.assert_called_once_with(provider="oidc", provider_account_id="akadmin")
        complete.assert_called_once()
