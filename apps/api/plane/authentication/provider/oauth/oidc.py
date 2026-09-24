# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

import pytz
import requests
from django.core.cache import cache
from jwt import PyJWKClient, decode as jwt_decode
from jwt.exceptions import InvalidTokenError, PyJWKClientError

# Module imports
from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)
from plane.authentication.adapter.oauth import OauthAdapter
from plane.license.utils.instance_value import get_configuration_value

_ALLOWED_ALGS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
_JWKS_CLIENTS: dict[str, PyJWKClient] = {}


def _pkce_pair():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _normalize_issuer(raw):
    if not raw or not isinstance(raw, str):
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
            error_message="OIDC_NOT_CONFIGURED",
        )
    parsed = urlparse(raw.strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
            error_message="OIDC_NOT_CONFIGURED",
        )
    if parsed.query or parsed.fragment:
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
            error_message="OIDC_NOT_CONFIGURED",
        )
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _absolute_endpoint(url, issuer_scheme):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
            error_message="OIDC_OAUTH_PROVIDER_ERROR",
        )
    if issuer_scheme == "https" and parsed.scheme != "https":
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
            error_message="OIDC_OAUTH_PROVIDER_ERROR",
        )
    return url


def _email_is_verified(claims):
    value = claims.get("email_verified")
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _split_name(claims):
    given = str(claims.get("given_name") or "").strip()
    family = str(claims.get("family_name") or "").strip()
    if given or family:
        return given[:255], family[:255]
    full = str(claims.get("name") or "").strip()
    if full:
        parts = full.split(" ", 1)
        return parts[0][:255], (parts[1] if len(parts) > 1 else "")[:255]
    preferred = str(claims.get("preferred_username") or "").strip()
    return preferred[:255], ""


class OIDCOAuthProvider(OauthAdapter):
    """Generic OpenID Connect provider (Authentik, Keycloak, and any other OIDC IdP)."""

    provider = "oidc"
    scope = "openid email profile"

    def __init__(self, request, code=None, state=None, callback=None, code_verifier=None):
        (enabled, client_id, client_secret, issuer_url) = get_configuration_value(
            [
                {"key": "IS_OIDC_ENABLED", "default": os.environ.get("IS_OIDC_ENABLED", "0")},
                {"key": "OIDC_CLIENT_ID", "default": os.environ.get("OIDC_CLIENT_ID")},
                {"key": "OIDC_CLIENT_SECRET", "default": os.environ.get("OIDC_CLIENT_SECRET")},
                {"key": "OIDC_ISSUER_URL", "default": os.environ.get("OIDC_ISSUER_URL")},
            ]
        )

        if enabled != "1" or not (client_id and client_secret and issuer_url):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
                error_message="OIDC_NOT_CONFIGURED",
            )

        issuer = _normalize_issuer(issuer_url)
        discovery = self._load_discovery(issuer)
        if discovery.get("issuer", "").rstrip("/") != issuer:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )

        issuer_scheme = urlparse(issuer).scheme
        self.token_url = _absolute_endpoint(discovery.get("token_endpoint"), issuer_scheme)
        self.userinfo_url = _absolute_endpoint(discovery.get("userinfo_endpoint"), issuer_scheme)
        self.jwks_uri = _absolute_endpoint(discovery.get("jwks_uri"), issuer_scheme)
        self.expected_issuer = discovery.get("issuer")
        supported = discovery.get("id_token_signing_alg_values_supported") or ["RS256"]
        self.algorithms = [alg for alg in supported if alg in _ALLOWED_ALGS] or ["RS256"]

        redirect_uri = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}/auth/oidc/callback/"
        self.code_verifier = code_verifier
        url_params = {
            "client_id": client_id,
            "scope": self.scope,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if code is None:
            verifier, challenge = _pkce_pair()
            self.code_verifier = verifier
            url_params["code_challenge"] = challenge
            url_params["code_challenge_method"] = "S256"
        auth_url = f"{_absolute_endpoint(discovery.get('authorization_endpoint'), issuer_scheme)}?{urlencode(url_params)}"

        self.id_token_claims = {}
        super().__init__(
            request,
            self.provider,
            client_id,
            self.scope,
            redirect_uri,
            auth_url,
            self.token_url,
            self.userinfo_url,
            client_secret,
            code,
            callback=callback,
        )

    def _load_discovery(self, issuer):
        cache_key = "oidc-discovery-" + hashlib.sha256(issuer.encode()).hexdigest()
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return cached
        try:
            response = requests.get(
                f"{issuer}/.well-known/openid-configuration",
                timeout=10,
                allow_redirects=False,
            )
            response.raise_for_status()
            document = response.json()
        except (requests.RequestException, ValueError):
            logging.getLogger("plane.authentication").warning("OIDC discovery document could not be loaded")
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )
        for key in ("issuer", "authorization_endpoint", "token_endpoint", "userinfo_endpoint", "jwks_uri"):
            if not document.get(key):
                raise AuthenticationException(
                    error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                    error_message="OIDC_OAUTH_PROVIDER_ERROR",
                )
        cache.set(cache_key, document, 300)
        return document

    def _validate_id_token(self, id_token):
        try:
            client = _JWKS_CLIENTS.get(self.jwks_uri)
            if client is None:
                client = PyJWKClient(self.jwks_uri, cache_keys=True, lifespan=300, timeout=10)
                _JWKS_CLIENTS[self.jwks_uri] = client
            signing_key = client.get_signing_key_from_jwt(id_token)
            return jwt_decode(
                id_token,
                signing_key.key,
                algorithms=self.algorithms,
                audience=self.client_id,
                issuer=self.expected_issuer,
                options={"require": ["exp", "sub"]},
            )
        except (InvalidTokenError, PyJWKClientError, ValueError):
            self.logger.warning("OIDC id_token failed validation")
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )

    def set_token_data(self):
        if not self.code_verifier:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )
        data = {
            "code": self.code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": self.code_verifier,
        }
        token_response = self.get_user_token(data=data, headers={"Accept": "application/json"})
        id_token = token_response.get("id_token") or ""
        if not id_token:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )
        self.id_token_claims = self._validate_id_token(id_token)
        super().set_token_data(
            {
                "access_token": token_response.get("access_token"),
                "refresh_token": token_response.get("refresh_token", None),
                "access_token_expired_at": (
                    datetime.now(tz=pytz.utc) + timedelta(seconds=token_response.get("expires_in"))
                    if token_response.get("expires_in")
                    else None
                ),
                "refresh_token_expired_at": (
                    datetime.fromtimestamp(token_response.get("refresh_token_expired_at"), tz=pytz.utc)
                    if token_response.get("refresh_token_expired_at")
                    else None
                ),
                "id_token": id_token,
            }
        )

    def set_user_data(self):
        profile = {}
        try:
            profile = self.get_user_response() or {}
        except AuthenticationException:
            self.logger.warning("OIDC userinfo request failed; using verified id_token claims")

        if profile.get("sub") and profile.get("sub") != self.id_token_claims.get("sub"):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
                error_message="OIDC_OAUTH_PROVIDER_ERROR",
            )

        claims = dict(self.id_token_claims)
        claims.update({key: value for key, value in profile.items() if value is not None})

        if not _email_is_verified(claims):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OAUTH_PROVIDER_UNVERIFIED_EMAIL"],
                error_message="OAUTH_PROVIDER_UNVERIFIED_EMAIL",
            )

        email = claims.get("email")
        first_name, last_name = _split_name(claims)
        super().set_user_data(
            {
                "email": email,
                "user": {
                    "provider_id": str(claims.get("sub") or ""),
                    "email": email,
                    "avatar": claims.get("picture") or "",
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_password_autoset": True,
                },
            }
        )
