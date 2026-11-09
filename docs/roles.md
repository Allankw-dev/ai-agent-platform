# Roles and permissions

Roles within an organization: **owner > admin > developer > member**. A platform-level
`is_super_admin` flag exists on users for the future super administrator dashboard (Phase 8); it
grants nothing inside organizations today.

| Action | Owner | Admin | Developer | Member |
| --- | :-: | :-: | :-: | :-: |
| View the organization and its members | yes | yes | yes | yes |
| Rename the organization | yes | yes | no | no |
| Delete the organization | yes | no | no | no |
| Invite people, view and revoke invitations | yes | yes | no | no |
| Change roles / remove others | yes | below own level | no | no |
| Leave the organization | yes* | yes | yes | yes |

\* unless they are the last owner.

## Hierarchy rules

- You can only change or remove someone ranked **below** you. Owners can manage anyone, including
  other owners.
- You can only grant roles ranked **below** your own. Only owners can create admins or owners.
- Nobody can change their own role.
- An organization always keeps at least one owner; the last owner cannot leave or be demoted.
- Ownership cannot be granted by invitation: invite as admin or lower, then promote.
- Non-members receive `404 organization_not_found` for every organization route, so organization
  ids cannot be probed.

## Invitations

- The owner or an admin creates one; the response contains a one-time link
  (`<FRONTEND_URL>/invite/<token>`). Only a SHA-256 hash of the token is stored, so the link
  cannot be shown again. Email delivery is not built yet: share the link yourself.
- Invitations expire after 7 days (`INVITATION_TTL_DAYS`).
- To accept, the person signs in with the **same email** the invitation was sent to, and that email
  must be confirmed: the API checks this with Supabase's Auth server (see `docs/auth.md`).
- One open invitation per email per organization; expired ones no longer block a new one.

Every change above is written to the audit log.
