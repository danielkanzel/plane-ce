# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.utils import timezone
from django.db.models import Q

# Third party imports
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

# Module imports
from plane.authentication.adapter.error import AuthenticationException
from plane.authentication.provider.oauth.oidc import authenticate_oidc_api_token
from plane.db.models import APIToken

_OIDC_API_DETAIL = {
    "OIDC_NOT_CONFIGURED": "OIDC API authentication is not configured",
    "OIDC_OAUTH_PROVIDER_ERROR": "OIDC access token is not valid",
    "USER_DOES_NOT_EXIST": "No Plane user is linked to this login",
    "USER_ACCOUNT_DEACTIVATED": "Plane user is deactivated",
}


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authentication with an API Key
    """

    www_authenticate_realm = "api"
    media_type = "application/json"
    auth_header_name = "X-Api-Key"

    def get_api_token(self, request):
        return request.headers.get(self.auth_header_name)

    def validate_api_token(self, token):
        # ToolHive's access token is a JWT. The shim forwards it unchanged,
        # and the Plane MCP server sends it here as X-Api-Key. An opaque
        # plane_api_* key stays on the path below.
        if isinstance(token, str) and token.count(".") == 2 and token.startswith("eyJ"):
            try:
                user = authenticate_oidc_api_token(token)
            except AuthenticationException as exc:
                raise AuthenticationFailed(_OIDC_API_DETAIL.get(exc.error_message, "OIDC access token is not valid"))
            return (user, token)

        try:
            api_token = APIToken.objects.get(
                Q(Q(expired_at__gt=timezone.now()) | Q(expired_at__isnull=True)),
                token=token,
                is_active=True,
                user__is_active=True,
            )
        except APIToken.DoesNotExist:
            raise AuthenticationFailed("Given API token is not valid")

        # save api token last used
        api_token.last_used = timezone.now()
        api_token.save(update_fields=["last_used"])
        return (api_token.user, api_token.token)

    def authenticate(self, request):
        token = self.get_api_token(request=request)
        if not token:
            return None

        # Validate the API token
        user, token = self.validate_api_token(token)
        return user, token
