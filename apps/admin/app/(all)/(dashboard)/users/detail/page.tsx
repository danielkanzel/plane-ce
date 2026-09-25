/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { useParams } from "react-router";
import { useRouter } from "next/navigation";
import { Button } from "@makeplane/propel/components/button";
import { Input } from "@makeplane/propel/components/input";
import { Switch } from "@makeplane/propel/components/switch";
import { InstanceUserService } from "@plane/services";
import { setToast } from "@plane/blocks/toast";
import { PageWrapper } from "@/components/common/page-wrapper";
import { Skeleton } from "@/components/common/skeleton";
import type { Route } from "./+types/page";

const instanceUserService = new InstanceUserService();

function errorText(error: unknown, fallback: string) {
  if (error && typeof error === "object" && "error" in error && typeof error.error === "string") return error.error;
  return fallback;
}

function UserDetailPage(_props: Route.ComponentProps) {
  const { userId } = useParams();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [isEmailVerified, setIsEmailVerified] = useState(false);
  const [isInstanceAdmin, setIsInstanceAdmin] = useState(false);
  const [oidcSubject, setOidcSubject] = useState("");
  const [saving, setSaving] = useState(false);
  const [linking, setLinking] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data, isLoading, mutate } = useSWR(userId ? ["INSTANCE_USER", userId] : null, async () => {
    const user = await instanceUserService.retrieve(userId!);
    setEmail(user.email);
    setFirstName(user.first_name);
    setLastName(user.last_name);
    setDisplayName(user.display_name);
    setIsActive(user.is_active);
    setIsEmailVerified(user.is_email_verified);
    setIsInstanceAdmin(user.is_instance_admin);
    setOidcSubject(user.oidc_account?.provider_account_id ?? "");
    return user;
  });

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!userId) return;
    setSaving(true);
    try {
      const user = await instanceUserService.update(userId, {
        email,
        first_name: firstName,
        last_name: lastName,
        display_name: displayName,
        password: password || undefined,
        is_active: isActive,
        is_email_verified: isEmailVerified,
        is_instance_admin: isInstanceAdmin,
      });
      setPassword("");
      await mutate(user, { revalidate: false });
      setToast({ type: "success", title: "User saved", message: user.email });
    } catch (error) {
      setToast({ type: "error", title: "Could not save user", message: errorText(error, "User could not be saved.") });
    } finally {
      setSaving(false);
    }
  };

  const link = async () => {
    if (!userId) return;
    setLinking(true);
    try {
      const user = await instanceUserService.linkOidc(userId, oidcSubject);
      await mutate(user, { revalidate: false });
      setToast({ type: "success", title: "Authentik linked", message: oidcSubject });
    } catch (error) {
      setToast({
        type: "error",
        title: "Could not link Authentik",
        message: errorText(error, "Authentik subject could not be linked."),
      });
    } finally {
      setLinking(false);
    }
  };

  const unlink = async () => {
    if (!userId) return;
    setLinking(true);
    try {
      const user = await instanceUserService.unlinkOidc(userId);
      setOidcSubject("");
      await mutate(user, { revalidate: false });
      setToast({ type: "success", title: "Authentik unlinked", message: "The user can no longer sign in with this subject." });
    } catch (error) {
      setToast({
        type: "error",
        title: "Could not unlink Authentik",
        message: errorText(error, "Authentik link could not be removed."),
      });
    } finally {
      setLinking(false);
    }
  };

  const remove = async () => {
    if (!userId) return;
    setSaving(true);
    try {
      await instanceUserService.remove(userId);
      setToast({ type: "success", title: "User deleted", message: email });
      router.push("/users");
    } catch (error) {
      setToast({ type: "error", title: "Could not delete user", message: errorText(error, "User could not be deleted.") });
      setSaving(false);
    }
  };

  if (isLoading || !data) {
    return (
      <PageWrapper header={{ title: "User", description: "Loading account." }}>
        <Skeleton>
          <Skeleton.Item height="240px" width="100%" />
        </Skeleton>
      </PageWrapper>
    );
  }

  return (
    <PageWrapper
      header={{
        title: data.display_name || data.email,
        description: `Joined ${new Date(data.date_joined).toLocaleString()}. Last sign-in method: ${data.last_login_medium}.`,
      }}
    >
      <form className="mx-4 flex max-w-xl flex-col gap-4" onSubmit={(event) => void save(event)}>
        <label className="flex flex-col gap-1 text-13">
          Email
          <Input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-13">
          First name
          <Input value={firstName} onChange={(event) => setFirstName(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-13">
          Last name
          <Input value={lastName} onChange={(event) => setLastName(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-13">
          Display name
          <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-13">
          New password
          <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" />
        </label>
        <div className="flex items-center justify-between gap-4">
          <span className="text-13">Active</span>
          <Switch checked={isActive} onCheckedChange={setIsActive} aria-label="Active" />
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-13">Email verified</span>
          <Switch checked={isEmailVerified} onCheckedChange={setIsEmailVerified} aria-label="Email verified" />
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-13">Instance admin</span>
          <Switch checked={isInstanceAdmin} onCheckedChange={setIsInstanceAdmin} aria-label="Instance admin" />
        </div>
        <Button type="submit" variant="primary" size="sm" stretch="auto" loading={saving} label="Save" />
      </form>

      <div className="mx-4 mt-8 flex max-w-xl flex-col gap-3 border-t border-subtle pt-6">
        <h2 className="text-16 font-medium">Authentik</h2>
        <p className="text-12 text-tertiary">
          Subject is the Authentik username for this instance. The user must have that username and a non-empty email.
        </p>
        <Input
          value={oidcSubject}
          onChange={(event) => setOidcSubject(event.target.value)}
          placeholder="Authentik username"
          aria-label="Authentik username"
        />
        <div className="flex gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            stretch="auto"
            loading={linking}
            label={data.oidc_account ? "Update link" : "Link Authentik"}
            onClick={() => void link()}
          />
          {data.oidc_account && (
            <Button type="button" variant="ghost" size="sm" stretch="auto" label="Unlink" onClick={() => void unlink()} />
          )}
        </div>
      </div>

      <div className="mx-4 mt-8 flex max-w-xl flex-col gap-3 border-t border-subtle pt-6">
        <h2 className="text-16 font-medium">Delete user</h2>
        <p className="text-12 text-tertiary">
          Deleting removes the account. If the user still owns workspace data, deactivate them instead.
        </p>
        {confirmDelete ? (
          <div className="flex gap-2">
            <Button type="button" variant="primary" size="sm" stretch="auto" loading={saving} label="Confirm delete" onClick={() => void remove()} />
            <Button type="button" variant="secondary" size="sm" stretch="auto" label="Cancel" onClick={() => setConfirmDelete(false)} />
          </div>
        ) : (
          <Button type="button" variant="secondary" size="sm" stretch="auto" label="Delete user" onClick={() => setConfirmDelete(true)} />
        )}
      </div>
    </PageWrapper>
  );
}

export const meta: Route.MetaFunction = () => [{ title: "Edit user - God Mode" }];

export default UserDetailPage;
