"use client";

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Session } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, setTokenGetter } from "@/lib/api";
import { accessToken, supabase } from "@/lib/supabase";

export interface Me {
  id: string;
  email: string | null;
  display_name: string | null;
  role: "public" | "resident" | "surveyor" | "analyst" | "admin";
  home_h3: string | null;
  home_area: { slug: string; name: string } | null;
  verified: boolean;
  consent_version: string | null;
  current_consent_version: string;
  needs_consent: boolean;
}

interface AuthState {
  session: Session | null;
  ready: boolean;
  configured: boolean;
  me: Me | null;
  refreshMe: () => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  session: null,
  ready: false,
  configured: false,
  me: null,
  refreshMe: () => {},
  signOut: async () => {},
});

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

setTokenGetter(accessToken);

function AuthProvider({ children }: { children: ReactNode }) {
  const sb = supabase();
  const qc = useQueryClient();
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(!sb);

  useEffect(() => {
    if (!sb) return;
    sb.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data } = sb.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      setReady(true);
      qc.invalidateQueries({ queryKey: ["me"] });
    });
    return () => data.subscription.unsubscribe();
  }, [sb, qc]);

  const me = useQuery({
    queryKey: ["me", session?.user.id ?? null],
    queryFn: () => api<Me>("/me"),
    enabled: !!session,
    staleTime: 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
  });

  const value = useMemo<AuthState>(
    () => ({
      session,
      ready,
      configured: !!sb,
      me: session ? (me.data ?? null) : null,
      refreshMe: () => void me.refetch(),
      signOut: async () => {
        await sb?.auth.signOut();
        qc.removeQueries({ queryKey: ["me"] });
      },
    }),
    [session, ready, sb, me, qc],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60_000,
            refetchOnWindowFocus: false,
            retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
