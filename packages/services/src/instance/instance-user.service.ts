/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TPaginatedResponse } from "@plane/types";
import { APIService } from "../api.service";

export type TInstanceUserOidcAccount = {
  id: string;
  provider_account_id: string;
};

export type TInstanceUser = {
  id: string;
  email: string;
  display_name: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_email_verified: boolean;
  is_password_autoset: boolean;
  is_instance_admin: boolean;
  last_login_medium: string;
  last_login_time: string | null;
  date_joined: string;
  oidc_account: TInstanceUserOidcAccount | null;
};

export type TInstanceUserWrite = {
  email?: string;
  display_name?: string;
  first_name?: string;
  last_name?: string;
  password?: string;
  is_active?: boolean;
  is_email_verified?: boolean;
  is_instance_admin?: boolean;
  oidc_subject?: string;
};

export class InstanceUserService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  async list(cursor?: string, search?: string): Promise<TPaginatedResponse<TInstanceUser[]>> {
    return this.get("/api/instances/users/", {
      params: {
        cursor,
        search: search || undefined,
      },
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async retrieve(userId: string): Promise<TInstanceUser> {
    return this.get(`/api/instances/users/${userId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async create(data: TInstanceUserWrite): Promise<TInstanceUser> {
    return this.post("/api/instances/users/", data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async update(userId: string, data: TInstanceUserWrite): Promise<TInstanceUser> {
    return this.patch(`/api/instances/users/${userId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async remove(userId: string): Promise<void> {
    return this.delete(`/api/instances/users/${userId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async linkOidc(userId: string, providerAccountId: string): Promise<TInstanceUser> {
    return this.post(`/api/instances/users/${userId}/oidc/`, { provider_account_id: providerAccountId })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async unlinkOidc(userId: string): Promise<TInstanceUser> {
    return this.delete(`/api/instances/users/${userId}/oidc/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
