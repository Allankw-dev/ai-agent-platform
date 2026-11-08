"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/features/auth/auth-provider";
import { useChangeRole, useMembers, useRemoveMember } from "@/lib/api/queries";
import type { Member, OrgRole } from "@/lib/api/types";
import { ROLE_LABELS, ROLES, canAssign, canManage, canManageMembers } from "@/lib/permissions";

const PAGE_SIZE = 50;

export function MembersPanel({ orgId, myRole }: { orgId: string; myRole: OrgRole }) {
  const router = useRouter();
  const { user } = useAuth();
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [confirming, setConfirming] = useState<string | null>(null);
  const members = useMembers(orgId, limit);
  const changeRole = useChangeRole(orgId);
  const removeMember = useRemoveMember(orgId);

  const me = user?.id;
  const mayManage = canManageMembers(myRole);

  function remove(member: Member) {
    const leaving = member.user_id === me;
    removeMember.mutate(member.user_id, {
      onSuccess: () => {
        setConfirming(null);
        if (leaving) router.replace("/dashboard");
      },
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>
          {members.data
            ? `${members.data.total} ${members.data.total === 1 ? "person" : "people"} in this organization.`
            : "People in this organization."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ErrorNotice error={members.error ?? changeRole.error ?? removeMember.error} />
        {members.isPending && !members.error && <Spinner label="Loading members" />}
        {members.data && (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {members.data.items.map((member) => {
              const isMe = member.user_id === me;
              const editable = mayManage && !isMe && canManage(myRole, member.role);
              const removable = isMe || (mayManage && canManage(myRole, member.role));
              const roleOptions = ROLES.filter(
                (role) => canAssign(myRole, role) || role === member.role,
              );
              const busy =
                (changeRole.isPending && changeRole.variables?.userId === member.user_id) ||
                (removeMember.isPending && removeMember.variables === member.user_id);

              return (
                <li
                  key={member.user_id}
                  className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {member.full_name ?? member.email}
                      {isMe && (
                        <Badge variant="accent" className="ml-2">
                          You
                        </Badge>
                      )}
                    </p>
                    {member.full_name && (
                      <p className="truncate text-xs text-muted-foreground">{member.email}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {editable ? (
                      <Select
                        aria-label={`Role for ${member.email}`}
                        value={member.role}
                        disabled={busy}
                        onChange={(event) =>
                          changeRole.mutate({
                            userId: member.user_id,
                            role: event.target.value as OrgRole,
                          })
                        }
                      >
                        {roleOptions.map((role) => (
                          <option key={role} value={role}>
                            {ROLE_LABELS[role]}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Badge variant={member.role === "owner" ? "default" : "muted"}>
                        {ROLE_LABELS[member.role]}
                      </Badge>
                    )}
                    {removable &&
                      (confirming === member.user_id ? (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            className="border-danger/60 text-danger hover:bg-danger/10"
                            disabled={busy}
                            onClick={() => remove(member)}
                          >
                            {isMe ? "Confirm leave" : "Confirm remove"}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={`${isMe ? "Leave" : "Remove"} ${member.email}`}
                          onClick={() => setConfirming(member.user_id)}
                        >
                          {isMe ? "Leave" : "Remove"}
                        </Button>
                      ))}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {members.data && members.data.total > members.data.items.length && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setLimit((value) => value + PAGE_SIZE)}
          >
            Show more
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
