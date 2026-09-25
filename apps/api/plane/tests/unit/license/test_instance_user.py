# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.license.utils.instance_user import (
    normalize_email,
    normalize_name,
    normalize_oidc_subject,
    normalize_password,
)


@pytest.mark.unit
class TestInstanceUserNormalization:
    def test_email_is_stripped_and_lowered(self):
        assert normalize_email("  Ada@Example.com ") == "ada@example.com"

    def test_email_rejects_blank_and_invalid(self):
        with pytest.raises(ValueError):
            normalize_email("  ")
        with pytest.raises(ValueError):
            normalize_email("not-an-email")

    def test_name_length(self):
        assert normalize_name(None, "First name") == ""
        with pytest.raises(ValueError):
            normalize_name("a" * 256, "First name")

    def test_oidc_subject(self):
        assert normalize_oidc_subject("  akadmin ") == "akadmin"
        with pytest.raises(ValueError):
            normalize_oidc_subject("   ")

    def test_password_optional_and_bounded(self):
        assert normalize_password(None) is None
        assert normalize_password("") is None
        assert normalize_password("long-enough") == "long-enough"
        with pytest.raises(ValueError):
            normalize_password("short")
