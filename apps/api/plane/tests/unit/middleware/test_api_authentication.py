# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Unit tests for APIKeyAuthentication.

Covers the access-control guarantees of the external API key authentication:
- a valid token belonging to an active user authenticates successfully
- a valid token is rejected once the underlying user account is deactivated
  (prevents an authentication bypass via a disabled account that still holds
  a previously generated API key)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.exceptions import AuthenticationFailed

from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.authentication.provider.oauth import oidc as oidc_mod
from plane.db.models import APIToken, Account

API_ISSUER = "https://authentik.example.com/application/o/mcp"
API_DISCOVERY = {
    "issuer": API_ISSUER,
    "authorization_endpoint": f"{API_ISSUER}/authorize/",
    "token_endpoint": f"{API_ISSUER}/token/",
    "userinfo_endpoint": f"{API_ISSUER}/userinfo/",
    "jwks_uri": f"{API_ISSUER}/jwks/",
    "id_token_signing_alg_values_supported": ["RS256"],
}


@pytest.mark.unit
class TestAPIKeyAuthentication:
    @pytest.mark.django_db
    def test_validate_api_token_authenticates_active_user(self, create_user):
        token = APIToken.objects.create(
            user=create_user, label="Active Token", token="active-user-token"
        )

        user, returned_token = APIKeyAuthentication().validate_api_token(token.token)

        assert user == create_user
        assert returned_token == token.token

    @pytest.mark.django_db
    def test_validate_api_token_rejects_deactivated_user(self, create_user):
        token = APIToken.objects.create(
            user=create_user, label="Stale Token", token="deactivated-user-token"
        )

        # Account is deactivated by an administrator after the token was issued.
        create_user.is_active = False
        create_user.save()

        with pytest.raises(AuthenticationFailed):
            APIKeyAuthentication().validate_api_token(token.token)

    @pytest.mark.django_db
    def test_oidc_access_token_authenticates_linked_user(self, create_user):
        Account.objects.create(
            user=create_user,
            provider="oidc",
            provider_account_id="user-1",
            access_token="",
        )
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _access_token(private_key, sub="user-1", aud="mcp-hub")

        with _oidc_verifier(private_key):
            user, returned = APIKeyAuthentication().validate_api_token(token)

        assert user == create_user
        assert returned == token

    @pytest.mark.django_db
    def test_oidc_access_token_rejects_unlinked_subject(self, create_user):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _access_token(private_key, sub="nobody", aud="mcp-hub")

        with _oidc_verifier(private_key):
            with pytest.raises(AuthenticationFailed) as exc:
                APIKeyAuthentication().validate_api_token(token)

        assert "linked" in str(exc.value.detail)

    @pytest.mark.django_db
    def test_oidc_access_token_rejects_deactivated_user(self, create_user):
        Account.objects.create(
            user=create_user,
            provider="oidc",
            provider_account_id="user-1",
            access_token="",
        )
        create_user.is_active = False
        create_user.save()
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _access_token(private_key, sub="user-1", aud="mcp-hub")

        with _oidc_verifier(private_key):
            with pytest.raises(AuthenticationFailed) as exc:
                APIKeyAuthentication().validate_api_token(token)

        assert "deactivated" in str(exc.value.detail)

    @pytest.mark.django_db
    def test_oidc_access_token_rejects_wrong_audience(self, create_user):
        Account.objects.create(
            user=create_user,
            provider="oidc",
            provider_account_id="user-1",
            access_token="",
        )
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _access_token(private_key, sub="user-1", aud="someone-else")

        with _oidc_verifier(private_key):
            with pytest.raises(AuthenticationFailed) as exc:
                APIKeyAuthentication().validate_api_token(token)

        assert "not valid" in str(exc.value.detail)


def _access_token(private_key, **claims):
    now = datetime.now(timezone.utc)
    payload = {
        "iss": API_ISSUER,
        "exp": now + timedelta(minutes=5),
        "iat": now,
    }
    payload.update(claims)
    return jwt.encode(payload, private_key, algorithm="RS256")


def _oidc_verifier(private_key):
    oidc_mod._JWKS_CLIENTS.clear()
    signing_key = MagicMock()
    signing_key.key = private_key.public_key()
    jwk = patch("plane.authentication.provider.oauth.oidc.PyJWKClient")
    cache = patch("plane.authentication.provider.oauth.oidc.cache")
    config = patch(
        "plane.authentication.provider.oauth.oidc.get_configuration_value",
        return_value=("1", API_ISSUER, "mcp-hub"),
    )

    class _Stack:
        def __enter__(self):
            self.jwk = jwk.start()
            self.cache = cache.start()
            self.config = config.start()
            self.cache.get.return_value = API_DISCOVERY
            self.jwk.return_value.get_signing_key_from_jwt.return_value = signing_key
            return self

        def __exit__(self, *exc):
            config.stop()
            cache.stop()
            jwk.stop()
            oidc_mod._JWKS_CLIENTS.clear()

    return _Stack()
