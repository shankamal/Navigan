"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { User } from "oidc-client-ts";
import { authConfigured, authManager, identity } from "./session";
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
    if (!authConfigured) {
      setState({ identity: null, loading: false, configured: false });
      return;
    }
    let active = true;
    let lastIdentity = "";
    const client = authManager();
    const loaded = (user: User) => {
      const nextIdentity = user.expired ? null : identity(user);
      const fingerprint = JSON.stringify(nextIdentity);
      if (lastIdentity && lastIdentity !== fingerprint) cache.clear();
      lastIdentity = fingerprint;
      if (active)
        setState({ identity: nextIdentity, loading: false, configured: true });
    };
    const cleared = () => {
      cache.clear();
      if (active)
        setState({ identity: null, loading: false, configured: true });
    };
    const expired = () => {
      void client.removeUser();
    };
    client.events.addUserLoaded(loaded);
    client.events.addUserUnloaded(cleared);
    client.events.addAccessTokenExpired(expired);
    client.events.addSilentRenewError(expired);
    void client
      .getUser()
      .then((user) => {
        if (!active) return;
        if (user) loaded(user);
        else cleared();
      })
      .catch(cleared);
    return () => {
      active = false;
      client.events.removeUserLoaded(loaded);
      client.events.removeUserUnloaded(cleared);
      client.events.removeAccessTokenExpired(expired);
      client.events.removeSilentRenewError(expired);
    };
  }, [cache]);
  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}
export const useAuth = () => useContext(AuthContext);
