"use client";

import { createContext, useContext } from "react";

import type { Organization } from "@/lib/api/types";

const OrgContext = createContext<Organization | null>(null);

export const OrgProvider = OrgContext.Provider;

/** The organization of the current /orgs/[orgId] route, including the caller's role in it. */
export function useCurrentOrg(): Organization {
  const org = useContext(OrgContext);
  if (!org) throw new Error("useCurrentOrg must be used inside an organization page.");
  return org;
}
