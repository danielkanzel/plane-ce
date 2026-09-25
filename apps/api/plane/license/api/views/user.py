# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

from django.db import IntegrityError
from django.db.models import ProtectedError, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.db.models import Account, Profile, User
from plane.license.api.permissions import InstanceAdminPermission
from plane.license.models import Instance, InstanceAdmin
from plane.license.utils.instance_user import (
    normalize_email,
    normalize_name,
    normalize_oidc_subject,
    normalize_password,
)


def _instance():
    return Instance.objects.first()


def _is_instance_admin(user):
    instance = _instance()
    if instance is None:
        return False
    return InstanceAdmin.objects.filter(instance=instance, user=user).exists()


def _oidc_account(user):
    return Account.objects.filter(user=user, provider="oidc").first()


def _serialize_user(user):
    account = _oidc_account(user)
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": user.is_active,
        "is_email_verified": user.is_email_verified,
        "is_password_autoset": user.is_password_autoset,
        "is_instance_admin": _is_instance_admin(user),
        "last_login_medium": user.last_login_medium,
        "last_login_time": user.last_login_time,
        "date_joined": user.date_joined,
        "oidc_account": (
            {"id": str(account.id), "provider_account_id": account.provider_account_id} if account else None
        ),
    }


def _human_users():
    return User.objects.filter(is_bot=False)


def _get_user(pk):
    return _human_users().filter(pk=pk).first()


def _link_oidc(user, subject):
    provider_account_id = normalize_oidc_subject(subject)
    taken = Account.objects.filter(provider="oidc", provider_account_id=provider_account_id).exclude(user=user)
    if taken.exists():
        raise IntegrityError()
    account = _oidc_account(user)
    if account:
        account.provider_account_id = provider_account_id
        account.last_connected_at = timezone.now()
        account.save(update_fields=["provider_account_id", "last_connected_at", "updated_at"])
        return account
    return Account.objects.create(
        user=user,
        provider="oidc",
        provider_account_id=provider_account_id,
        access_token="",
        id_token="",
    )


def _set_instance_admin(user, enabled):
    instance = _instance()
    if instance is None:
        raise ValueError("Instance is not configured")
    existing = InstanceAdmin.objects.filter(instance=instance, user=user).first()
    if enabled and existing is None:
        InstanceAdmin.objects.create(instance=instance, user=user, role=20, is_verified=True)
    if not enabled and existing is not None:
        if InstanceAdmin.objects.filter(instance=instance).count() <= 1:
            raise ValueError("The last instance admin cannot be removed")
        existing.delete()


class InstanceUserEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        users = _human_users().order_by("-created_at")
        search = (request.query_params.get("search") or "").strip()
        if search:
            users = users.filter(
                Q(email__icontains=search)
                | Q(display_name__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        return self.paginate(
            request=request,
            queryset=users,
            on_results=lambda results: [_serialize_user(user) for user in results],
            max_per_page=25,
            default_per_page=25,
        )

    def post(self, request):
        try:
            email = normalize_email(request.data.get("email"))
            first_name = normalize_name(request.data.get("first_name"), "First name")
            last_name = normalize_name(request.data.get("last_name"), "Last name")
            display_name = normalize_name(request.data.get("display_name"), "Display name") or User.get_display_name(
                email
            )
            password = normalize_password(request.data.get("password"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=email).exists():
            return Response({"error": "A user with this email already exists"}, status=status.HTTP_409_CONFLICT)

        user = User(
            email=email,
            username=uuid.uuid4().hex,
            first_name=first_name,
            last_name=last_name,
            display_name=display_name,
            is_active=True,
            is_email_verified=True,
            is_password_autoset=password is None,
        )
        user.set_password(password or uuid.uuid4().hex)
        try:
            user.save()
        except IntegrityError:
            return Response({"error": "A user with this email already exists"}, status=status.HTTP_409_CONFLICT)
        Profile.objects.get_or_create(user=user)

        subject = request.data.get("oidc_subject")
        if subject:
            try:
                _link_oidc(user, subject)
            except ValueError as exc:
                user.delete()
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            except IntegrityError:
                user.delete()
                return Response(
                    {"error": "This Authentik subject is already linked to another user"},
                    status=status.HTTP_409_CONFLICT,
                )

        if request.data.get("is_instance_admin") is True:
            try:
                _set_instance_admin(user, True)
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_user(user), status=status.HTTP_201_CREATED)


class InstanceUserDetailEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    def get(self, request, pk):
        user = _get_user(pk)
        if user is None:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_user(user), status=status.HTTP_200_OK)

    def patch(self, request, pk):
        user = _get_user(pk)
        if user is None:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        data = request.data
        try:
            if "email" in data:
                email = normalize_email(data.get("email"))
                if User.objects.filter(email=email).exclude(pk=user.pk).exists():
                    return Response({"error": "A user with this email already exists"}, status=status.HTTP_409_CONFLICT)
                user.email = email
            if "first_name" in data:
                user.first_name = normalize_name(data.get("first_name"), "First name")
            if "last_name" in data:
                user.last_name = normalize_name(data.get("last_name"), "Last name")
            if "display_name" in data:
                user.display_name = normalize_name(data.get("display_name"), "Display name") or user.display_name
            if "is_email_verified" in data:
                if not isinstance(data.get("is_email_verified"), bool):
                    raise ValueError("is_email_verified must be a boolean")
                user.is_email_verified = data.get("is_email_verified")
            if "is_active" in data:
                if not isinstance(data.get("is_active"), bool):
                    raise ValueError("is_active must be a boolean")
                if data.get("is_active") is False and user.id == request.user.id:
                    raise ValueError("You cannot deactivate your own account")
                user.is_active = data.get("is_active")
                if not user.is_active:
                    user.last_logout_time = timezone.now()
            if "password" in data:
                password = normalize_password(data.get("password"))
                if password:
                    user.set_password(password)
                    user.is_password_autoset = False
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user.save()
        except IntegrityError:
            return Response({"error": "A user with this email already exists"}, status=status.HTTP_409_CONFLICT)

        if "is_instance_admin" in data:
            if not isinstance(data.get("is_instance_admin"), bool):
                return Response({"error": "is_instance_admin must be a boolean"}, status=status.HTTP_400_BAD_REQUEST)
            try:
                if data.get("is_instance_admin") is False and user.id == request.user.id:
                    raise ValueError("You cannot remove your own instance admin role")
                _set_instance_admin(user, data.get("is_instance_admin"))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_user(user), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        user = _get_user(pk)
        if user is None:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        if user.id == request.user.id:
            return Response({"error": "You cannot delete your own account"}, status=status.HTTP_400_BAD_REQUEST)
        if _is_instance_admin(user):
            return Response(
                {"error": "Remove the instance admin role before deleting this user"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user.delete()
        except ProtectedError:
            return Response(
                {"error": "This user still owns data that cannot be deleted. Deactivate the account instead."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class InstanceUserOidcEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    def post(self, request, pk):
        user = _get_user(pk)
        if user is None:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            _link_oidc(user, request.data.get("provider_account_id"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"error": "This Authentik subject is already linked to another user"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(_serialize_user(user), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        user = _get_user(pk)
        if user is None:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        Account.objects.filter(user=user, provider="oidc").delete()
        return Response(_serialize_user(user), status=status.HTTP_200_OK)
