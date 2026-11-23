"use client";

import { useEffect, useState } from "react";

import { formatTimeLeft, secondsUntil } from "@/features/approvals/approval-format";
import type { Approval } from "@/lib/api/types";

/** The current time, refreshed every `intervalMs`, so a countdown stays right without a reload. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** "Expires in 5 h 12 min" for a waiting approval, and nothing for a decided one. */
export function ExpiryText({ approval }: { approval: Approval }) {
  const now = useNow(30_000);
  if (approval.status !== "pending") return null;
  if (!approval.expires_at) return <span>No expiry</span>;
  const left = secondsUntil(approval.expires_at, now);
  if (left <= 0) return <span>Expired</span>;
  return <span>Expires in {formatTimeLeft(left)}</span>;
}
