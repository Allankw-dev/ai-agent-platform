"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Session, User } from "@supabase/supabase-js";

import { getSupabase, isSupabaseConfigured, signOut as signOutOfSupabase } from "@/lib/supabase";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

type AuthState = {
  status: AuthStatus;
  session: Session | null;
  user: User | null;
  configured: boolean;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const configured = isSupabaseConfigured();
  const [session, setSession] = useState<Session | null>(null);
  const [loaded, setLoaded] = useState(!configured);
  const lastUserId = useRef<string | null>(null);

  useEffect(() => {
    if (!configured) return;
    const supabase = getSupabase();

    const apply = (next: Session | null) => {
      // Never leave one person's cached data around for the next person who signs in.
      const nextUserId = next?.user.id ?? null;
      if (lastUserId.current !== nextUserId) queryClient.clear();
      lastUserId.current = nextUserId;
      setSession(next);
      setLoaded(true);
    };

    void supabase.auth.getSession().then(({ data }) => apply(data.session));
    // Only update state in this callback; calling Supabase from here can deadlock.
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, next) => apply(next));
    return () => subscription.subscription.unsubscribe();
  }, [configured, queryClient]);

  const value = useMemo<AuthState>(
    () => ({
      status: !loaded ? "loading" : session ? "authenticated" : "unauthenticated",
      session,
      user: session?.user ?? null,
      configured,
      signOut: signOutOfSupabase,
    }),
    [loaded, session, configured],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>.");
  return context;
}
