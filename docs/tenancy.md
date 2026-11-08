# Tenant isolation (Row Level Security)

Isolation is enforced twice: the application scopes queries by `org_id`, and PostgreSQL refuses
to return or change another organization's rows even if the application gets it wrong.

## How a request is scoped

1. The API verifies the Supabase token, then (for organization routes) checks the user is a member
   of the requested organization.
2. It starts a database transaction and sets these settings with `set_config(..., is_local => true)`:
   - `app.user_id`: the authenticated user
   - `app.org_id`: the organization the request acts within
   - `app.invite_hash`: only while accepting an invitation (see below)
3. Policies compare every row against these settings. Unset or empty settings match nothing.
4. The settings disappear when the transaction ends, so a pooled connection can never carry one
   request's context into the next. `app/db/tenancy.py` re-applies them on each new transaction
   of the same session (for example after a commit).

Code must call `use_tenant(session, user_id=..., org_id=...)` before touching tenant data.
`app.org_id` is trusted input to the database, so only code that has verified membership may set
it. In practice that is `get_org_context` in `app/api/deps.py` (membership check for every
`/organizations/{org_id}/...` route), organization creation, and invitation acceptance.

## Policy summary (runtime role `agent_app`)

| Table | Read | Write |
| --- | --- | --- |
| agents, agent_versions, agent_tools, integrations, credentials, agent_runs, run_steps, approvals, conversations, messages, usage_records | `org_id` = current org | `org_id` = current org (checked on insert and update, so rows cannot be moved to another org) |
| organization_members | current org's rows, plus your own memberships in any org | current org only |
| organizations | the current org, plus any you belong to | insert only as yourself (`created_by_id`); update/delete current org |
| users | yourself, plus members of the current org | insert/update yourself only; never delete |
| organization_invitations | current org's rows, or the one row whose token hash equals `app.invite_hash` | current org only |
| audit_logs | current org | insert only, for the current org or with no org; no update or delete |
| tools | everyone (global catalog) | owner role only (migrations) |

Accepting an invitation: a person is not yet a member, so they cannot see the organization. The API
hashes the one-time token and sets `app.invite_hash`; the policy then reveals that single
invitation. After the API checks it (open, unexpired, email matches the signed-in user) it sets
`app.org_id` to the invitation's organization and adds the membership.

Creating an organization: generate the id, call `use_tenant(user_id=me, org_id=new_id)`, insert the
organization and your owner membership in one transaction.

## Beyond row policies

- Child tables reference parents by `(id, org_id)`, so a row can never link to another tenant's data.
- Row policies cannot protect single columns, so column privileges stop users from setting
  `users.is_super_admin` themselves.
- `FORCE ROW LEVEL SECURITY` is on, so the table owner is also subject to policies when it is not
  a superuser (as on Supabase). A superuser always bypasses RLS, which is why tests connect as the
  non-superuser runtime role.
- Roles (owner, admin, developer, member) are enforced by the API; the database enforces tenancy.

## Known limits

- Background workers must set `app.org_id` for the organization they act for, with no user.
- Migrations that backfill data must run as the owner and may need `SET row_security = off`.
