# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("A valid email is required")
    email = value.strip().lower()
    if not email:
        raise ValueError("A valid email is required")
    try:
        validate_email(email)
    except ValidationError:
        raise ValueError("A valid email is required")
    return email


def normalize_name(value, field):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    name = value.strip()
    if len(name) > 255:
        raise ValueError(f"{field} is too long")
    return name


def normalize_oidc_subject(value):
    if not isinstance(value, str):
        raise ValueError("Authentik subject is required")
    subject = value.strip()
    if not subject or len(subject) > 255:
        raise ValueError("Authentik subject must be 1-255 characters")
    return subject


def normalize_password(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) < 8 or len(value) > 128:
        raise ValueError("Password must be 8-128 characters")
    return value
