/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@makeplane/propel/components/button";
import { Input } from "@makeplane/propel/components/input";
import { Switch } from "@makeplane/propel/components/switch";
import { InstanceUserService } from "@plane/services";
import { setToast } from "@plane/blocks/toast";
import { PageWrapper } from "@/components/common/page-wrapper";
import type { Route } from "./+types/page";

const instanceUserService = new InstanceUserService();

function errorText(error: unknown) {
  if (error && typeof error === "object" && "error" in error && typeof error.error === "string") return error.error;
  return "User could not be created.";
}

function CreateUserPage(_props: Route.ComponentProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [oidcSubject, setOidcSubject] = useState("");
  const [isInstanceAdmin, setIsInstanceAdmin] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const user = await instanceUserService.create({
        email,
        first_name: firstName,
        last_name: lastName,
        display_name: displayName,
        password: password || undefined,
        oidc_subject: oidcSubject || undefined,
        is_instance_admin: isInstanceAdmin,
      });
      setToast({ type: "success", title: "User created", message: user.email });
      router.push(`/users/${user.id}`);
    } catch (error) {
      setToast({ type: "error", title: "Could not create user", message: errorText(error) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <PageWrapper
      header={{
        title: "Create user",
        description: "The account can sign in with a password, or only through Authentik if you leave the password empty.",
      }}
    >
      <form className="mx-4 flex max-w-xl flex-col gap-4" onSubmit={(event) => void onSubmit(event)}>
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
          Password
          <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" />
        </label>
        <label className="flex flex-col gap-1 text-13">
          Authentik username
          <Input
            value={oidcSubject}
            onChange={(event) => setOidcSubject(event.target.value)}
            placeholder="Subject from Authentik, usually the username"
          />
        </label>
        <div className="flex items-center justify-between gap-4">
          <span className="text-13">Instance admin</span>
          <Switch checked={isInstanceAdmin} onCheckedChange={setIsInstanceAdmin} aria-label="Instance admin" />
        </div>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" size="sm" stretch="auto" loading={submitting} label="Create" />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            stretch="auto"
            label="Cancel"
            onClick={() => router.push("/users")}
          />
        </div>
      </form>
    </PageWrapper>
  );
}

export const meta: Route.MetaFunction = () => [{ title: "Create user - God Mode" }];

export default CreateUserPage;
