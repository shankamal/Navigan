"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Hub } from "aws-amplify/utils";
import { useQueryClient } from "@tanstack/react-query";
import { authConfigured, configureAuth, currentIdentity } from "./session";
import type { Identity } from "./claims";
interface AuthState {
  identity: Identity | null;
  loading: boolean;
  configured: boolean;
}
const AuthContext = createContext<AuthState>({
  identity: null,
  loading: true,
  configured: authConfigured,
});
export function AuthProvider({ children }: { children: ReactNode }) {
  const cache = useQueryClient();
  const [state, setState] = useState<AuthState>({
    identity: null,
    loading: true,
    configured: authConfigured,
  });
  useEffect(() => {
    let active = true;
    let revision = 0;
    let fingerprint: string | undefined;
    let lastIdentity: Identity | null = null;
    const update = (identity: Identity | null) => {
      const next = JSON.stringify(identity);
      if (fingerprint !== next) cache.clear();
      fingerprint = next;
      lastIdentity = identity;
      if (active)
        setState({ identity, loading: false, configured: authConfigured });
    };
    const refresh = async () => {
      const request = ++revision;
      try {
        const identity = await currentIdentity();
        if (active && request === revision) update(identity);
      } catch {
        // A temporary authorization-service failure must not turn a valid
        // Cognito session into a misleading login failure. API authorization
        // remains enforced server-side. Explicit sign-out and token refresh
        // failures still clear the identity through the Hub listener below.
        if (active && request === revision) {
          if (lastIdentity) {
            setState({
              identity: lastIdentity,
              loading: false,
              configured: authConfigured,
            });
          } else {
            update(null);
          }
        }
      }
    };
    if (!authConfigured) {
      update(null);
      return;
    }
    try {
      configureAuth();
    } catch {
      update(null);
      return;
    }
    const cancel = Hub.listen("auth", ({ payload }) => {
      if (
        payload.event === "signedOut" ||
        payload.event === "tokenRefresh_failure"
      ) {
        revision++;
        update(null);
      } else if (
        payload.event === "signedIn" ||
        payload.event === "tokenRefresh"
      ) {
        void refresh();
      }
    });
    void refresh();
    // Refresh sessions when returning to a tab and while the app remains open.
    const onFocus = () => {
      void refresh();
    };
    window.addEventListener("focus", onFocus);
    const timer = window.setInterval(onFocus, 60_000);
    return () => {
      active = false;
      revision++;
      cancel();
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [cache]);
  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}
export const useAuth = () => useContext(AuthContext);
