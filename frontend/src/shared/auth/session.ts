"use client";
import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import { identityFromClaims, readAccessClaims, type Identity } from "./claims";
export const authConfigured = Boolean(process.env.NEXT_PUBLIC_OIDC_CLIENT_ID);
let manager: UserManager | undefined;
let renewing: Promise<User | null> | undefined;
let completing: Promise<User> | undefined;
export function authManager(): UserManager {
  if (typeof window === "undefined")
    throw new Error("Authentication is available in the browser.");
  if (!authConfigured)
    throw new Error("Configure the Cognito app client before signing in.");
  if (!manager) {
    const origin =
      process.env.NEXT_PUBLIC_APP_URL?.replace(/\/$/, "") ||
      window.location.origin;
    manager = new UserManager({
      authority:
        process.env.NEXT_PUBLIC_OIDC_AUTHORITY ||
        "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_GtWAW9Owz",
      client_id: process.env.NEXT_PUBLIC_OIDC_CLIENT_ID!,
      redirect_uri: `${origin}/auth/callback`,
      post_logout_redirect_uri: `${origin}/login`,
      response_type: "code",
      scope:
        process.env.NEXT_PUBLIC_OIDC_SCOPE ||
        "openid profile email navigan/api",
      automaticSilentRenew: true,
      monitorSession: false,
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
      stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
      loadUserInfo: false,
    });
  }
  return manager;
}
export async function accessToken(): Promise<string | null> {
  if (!authConfigured) return null;
  const client = authManager();
  let user = await client.getUser();
  if (!user) return null;
  if (user.expired || (user.expires_in ?? 0) < 30) {
    // Refresh token renewals only. Do not attempt hidden browser login flows for API requests.
    if (!user.refresh_token) {
      await client.removeUser();
      return null;
    }
    try {
      renewing ??= client.signinSilent().finally(() => {
        renewing = undefined;
      });
      user = await renewing;
    } catch {
      await client.removeUser();
      return null;
    }
  }
  return user?.access_token ?? null;
}
export function identity(user: User): Identity {
  return identityFromClaims({
    ...readAccessClaims(user.access_token),
    name: user.profile.name,
    email: user.profile.email,
  });
}
export function completeSignIn(): Promise<User> {
  // One authorization-code exchange even under React Strict Mode's repeated effect setup.
  completing ??= authManager().signinRedirectCallback();
  return completing;
}
export async function signOut(): Promise<void> {
  const client = authManager();
  await client.removeUser();
  const domain = process.env.NEXT_PUBLIC_COGNITO_DOMAIN;
  const origin =
    process.env.NEXT_PUBLIC_APP_URL?.replace(/\/$/, "") ||
    window.location.origin;
  if (domain) {
    const url = new URL("/logout", domain);
    url.searchParams.set("client_id", process.env.NEXT_PUBLIC_OIDC_CLIENT_ID!);
    url.searchParams.set("logout_uri", `${origin}/login`);
    window.location.assign(url.toString());
  } else window.location.assign("/login");
}
