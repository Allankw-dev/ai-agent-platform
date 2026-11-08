export type OrgRole = "owner" | "admin" | "developer" | "member";

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type UserProfile = {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  is_super_admin: boolean;
  created_at: string;
};

export type Organization = {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: OrgRole;
};

export type Member = {
  user_id: string;
  email: string;
  full_name: string | null;
  role: OrgRole;
  joined_at: string;
};

export type InvitationStatus = "pending" | "expired" | "accepted" | "revoked";

export type Invitation = {
  id: string;
  email: string;
  role: OrgRole;
  status: InvitationStatus;
  expires_at: string;
  created_at: string;
};

export type InvitationCreated = Invitation & { invite_url: string };

export type InvitationAccepted = {
  organization: { id: string; name: string; slug: string; created_at: string };
  role: OrgRole;
};
