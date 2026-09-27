"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import type { Session } from "@supabase/supabase-js";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";
import { getMe } from "@/lib/api";
import type { Me } from "@/lib/types";

interface AuthCtx {
  session: Session | null;
  me: Me | null;
  loading: boolean;
  configured: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export const useAuth = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside AuthProvider");
  return c;
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!supabaseConfigured) { setLoading(false); return; }
    const sb = getSupabase();
    sb.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data: sub } = sb.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  /* The role comes from the API, not from the browser.
     A client-side role is a suggestion; the server reads it from `profiles`
     under row-level security, which is the value that actually gates writes. */
  useEffect(() => {
    let cancelled = false;
    if (!session?.access_token) { setMe(null); return; }
    getMe(session.access_token)
      .then((m) => { if (!cancelled) setMe(m); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [session?.access_token]);

  const signIn = useCallback(async (email: string, password: string) => {
    setError(null);
    const { error: e } = await getSupabase().auth
      .signInWithPassword({ email, password });
    if (e) throw new Error(e.message);
  }, []);

  const signOut = useCallback(async () => {
    await getSupabase().auth.signOut();
    setMe(null);
  }, []);

  const value = useMemo<AuthCtx>(() => ({
    session, me, loading, configured: supabaseConfigured, error, signIn, signOut,
  }), [session, me, loading, error, signIn, signOut]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
