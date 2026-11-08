"use client";

import { InvitationsPanel } from "@/features/orgs/invitations-panel";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { MembersPanel } from "@/features/orgs/members-panel";
import { canManageMembers } from "@/lib/permissions";

export function OrgMembersPage() {
  const org = useCurrentOrg();
  return (
    <div className="max-w-3xl space-y-6">
      <MembersPanel orgId={org.id} myRole={org.role} />
      {canManageMembers(org.role) && <InvitationsPanel orgId={org.id} myRole={org.role} />}
    </div>
  );
}
