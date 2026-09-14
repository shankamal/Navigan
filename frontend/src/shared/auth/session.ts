"use client";
import { Amplify } from "aws-amplify";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { fetchAuthSession, signOut as cognitoSignOut } from "aws-amplify/auth";
import {
  identityFromClaims,
  isHumanReadableDisplayName,
  type Identity,
} from "./claims";

interface EffectiveAccessResponse {
  user: { userId: string; displayName: string };
  authorizationRevision: number;
  privileges: string[];
  scopes: Array<{
    type: "SELF" | "CUSTOMER" | "PLATFORM" | "RESOURCE";
    customerIds?: string[];
  }>;
  source: "DYNAMIC" | "LEGACY_CLAIMS";
}

export const authConfigured = Boolean(process.env.NEXT_PUBLIC_OIDC_CLIENT_ID);
let configured = false;
export function configureAuth(): void {
  if (typeof window === "undefined") return;
  if (!authConfigured)
    throw new Error(
      "Sign-in has not been configured. Contact your administrator.",
    );
  if (configured) return;
  const authority =
    process.env.NEXT_PUBLIC_OIDC_AUTHORITY ||
    "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_GtWAW9Owz";
  const userPoolId = new URL(authority).pathname
    .split("/")
    .filter(Boolean)
    .at(-1)!;
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId: process.env.NEXT_PUBLIC_OIDC_CLIENT_ID!,
      },
    },
  });
  // Keep credentials scoped to this browser tab; never store passwords.
  cognitoUserPoolsTokenProvider.setKeyValueStorage({
    async getItem(key) {
      return window.sessionStorage.getItem(key);
    },
    async setItem(key, value) {
      window.sessionStorage.setItem(key, value);
    },
    async removeItem(key) {
      window.sessionStorage.removeItem(key);
    },
    async clear() {
      for (const key of Object.keys(window.sessionStorage)) {
        if (key.startsWith("CognitoIdentityServiceProvider."))
          window.sessionStorage.removeItem(key);
      }
    },
  });
  configured = true;
}
export async function accessToken(): Promise<string | null> {
  if (!authConfigured) return null;
  configureAuth();
  // Amplify refreshes expired access tokens and coalesces concurrent refresh requests.
  const { tokens } = await fetchAuthSession();
  return tokens?.accessToken.toString() ?? null;
}
export async function currentIdentity(): Promise<Identity | null> {
  if (!authConfigured) return null;
  configureAuth();
  const { tokens } = await fetchAuthSession();
  if (!tokens) return null;
  const legacy = identityFromClaims({
    ...tokens.accessToken.payload,
    name: tokens.idToken?.payload.name,
    given_name: tokens.idToken?.payload.given_name,
    family_name: tokens.idToken?.payload.family_name,
    email: tokens.idToken?.payload.email,
    preferred_username: tokens.idToken?.payload.preferred_username,
    "cognito:username": tokens.idToken?.payload["cognito:username"],
  });
  const response = await fetch("/api/platform/access/me", {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${tokens.accessToken.toString()}`,
      "X-Correlation-ID": crypto.randomUUID(),
    },
    cache: "no-store",
  });
  if (response.ok) {
    const access = (await response.json()) as EffectiveAccessResponse;
    if (
      access?.user?.userId !== legacy.subject ||
      !Array.isArray(access.privileges) ||
      !Array.isArray(access.scopes)
    ) {
      throw new Error("The authorization service returned an invalid identity.");
    }
    const customerIds = access.scopes.flatMap((scope) =>
      scope.type === "CUSTOMER" ? scope.customerIds ?? [] : [],
    );
    return {
      ...legacy,
      displayName: isHumanReadableDisplayName(
        access.user.displayName,
        legacy.subject,
      )
        ? access.user.displayName.trim()
        : legacy.displayName,
      customerIds: [...new Set(customerIds)],
      platformScope: access.scopes.some((scope) => scope.type === "PLATFORM"),
      canCreate: access.privileges.includes("customer.create"),
      privileges: access.privileges,
      authorizationRevision: access.authorizationRevision,
      authorizationSource: access.source,
    };
  }
  // During additive rollout, older stacks do not yet expose /access/me.
  if ([404, 502, 503, 504].includes(response.status)) return legacy;
  throw new Error(`Authorization lookup failed with status ${response.status}.`);
}
export async function clearSession(): Promise<void> {
  configureAuth();
  await cognitoSignOut();
}
export async function signOut(): Promise<void> {
  await clearSession();
  window.location.assign("/login");
}
