import type { Session } from "@supabase/supabase-js";
import {
  type ReactNode,
  useEffect,
  useMemo,
  useState,
} from "react";

import { queryClient } from "../lib/queryClient";
import { supabase } from "../lib/supabase";
import { AuthContext, type AuthContextValue } from "./authContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const { data: authListener } = supabase.auth.onAuthStateChange(
      (event, nextSession) => {
        if (!active) return;
        setSession(nextSession);
        setIsLoading(false);
        if (event === "SIGNED_OUT") {
          queryClient.clear();
        }
      },
    );

    void supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setIsLoading(false);
    });

    return () => {
      active = false;
      authListener.subscription.unsubscribe();
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isLoading,
      async signIn(email, password) {
        const { data, error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (error) throw error;
        setSession(data.session);
      },
      async signOut() {
        queryClient.clear();
        const { error } = await supabase.auth.signOut({ scope: "local" });
        if (error) throw error;
      },
    }),
    [isLoading, session],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
