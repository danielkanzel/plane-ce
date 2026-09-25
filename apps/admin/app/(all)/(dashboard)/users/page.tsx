/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { LoadingOutline as LoaderIcon } from "@makeplane/propel/icons";
import { Button } from "@makeplane/propel/components/button";
import { Input } from "@makeplane/propel/components/input";
import { InstanceUserService, type TInstanceUser } from "@plane/services";
import { PageWrapper } from "@/components/common/page-wrapper";
import { Skeleton } from "@/components/common/skeleton";
import type { Route } from "./+types/page";

const instanceUserService = new InstanceUserService();

function UsersPage(_props: Route.ComponentProps) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState<TInstanceUser[]>([]);
  const [nextCursor, setNextCursor] = useState<string | undefined>();
  const [hasNext, setHasNext] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const { isLoading, mutate } = useSWR(["INSTANCE_USERS", query], async () => {
    const page = await instanceUserService.list(undefined, query);
    setUsers(page.results);
    setNextCursor(page.next_cursor);
    setHasNext(Boolean(page.next_page_results));
    return page;
  });

  const loadMore = async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const page = await instanceUserService.list(nextCursor, query);
      setUsers((current) => [...current, ...page.results]);
      setNextCursor(page.next_cursor);
      setHasNext(Boolean(page.next_page_results));
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <PageWrapper
      header={{
        title: "Users",
        description: "Create accounts, edit them, and link them to Authentik.",
        actions: (
          <Button
            variant="primary"
            size="sm"
            stretch="auto"
            nativeButton={false}
            render={<Link href="/users/create" />}
            label="Create user"
          />
        ),
      }}
    >
      <form
        className="flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(search.trim());
          void mutate();
        }}
      >
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name or email"
          aria-label="Search users"
        />
        <Button type="submit" variant="secondary" size="sm" stretch="auto" label="Search" />
      </form>
      {isLoading ? (
        <Skeleton className="space-y-3">
          <Skeleton.Item height="72px" width="100%" />
          <Skeleton.Item height="72px" width="100%" />
          <Skeleton.Item height="72px" width="100%" />
        </Skeleton>
      ) : (
        <div className="flex flex-col gap-3">
          {users.length === 0 && <p className="text-13 text-tertiary">No users match this search.</p>}
          {users.map((user) => (
            <Link
              key={user.id}
              href={`/users/${user.id}`}
              className="flex items-center justify-between gap-4 rounded-lg border border-subtle bg-layer-1 p-3 hover:bg-layer-1-hover"
            >
              <div className="min-w-0">
                <div className="truncate text-14 font-medium text-primary">{user.display_name || user.email}</div>
                <div className="truncate text-12 text-tertiary">{user.email}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-11 text-tertiary">
                {!user.is_active && <span>Inactive</span>}
                {user.is_instance_admin && <span>Admin</span>}
                <span>{user.oidc_account ? "Authentik linked" : "No Authentik link"}</span>
              </div>
            </Link>
          ))}
          {hasNext && (
            <div className="flex justify-center">
              <Button
                variant="ghost"
                size="md"
                stretch="auto"
                onClick={() => void loadMore()}
                loading={loadingMore}
                label="Load more"
              />
            </div>
          )}
          {loadingMore && <LoaderIcon className="mx-auto h-4 w-4 animate-spin" />}
        </div>
      )}
    </PageWrapper>
  );
}

export const meta: Route.MetaFunction = () => [{ title: "Users - God Mode" }];

export default UsersPage;
