"use client";
import { Amplify } from "aws-amplify";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { fetchAuthSession, signOut as cognitoSignOut } from "aws-amplify/auth";
import { identityFromClaims, type Identity } from "./claims";

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
  return identityFromClaims({
    ...tokens.accessToken.payload,
    name: tokens.idToken?.payload.name,
    email: tokens.idToken?.payload.email,
  });
}
export async function clearSession(): Promise<void> {
  configureAuth();
  await cognitoSignOut();
}
export async function signOut(): Promise<void> {
  await clearSession();
  window.location.assign("/login");
}
