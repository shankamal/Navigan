"use client";
import { useAuth } from "./auth-provider";
import dynamic from "next/dynamic";
import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loading } from "@/shared/components/ui";

const SignInScreen = dynamic(
  () => import("./sign-in-screen").then((module) => module.SignInScreen),
  { loading: () => <Loading label="Opening secure sign-in…" /> },
);

export function AuthGate({ children }: { children: ReactNode }) {
  const { identity, loading, configured } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const onLoginPage = pathname === "/login";

  useEffect(() => {
    if (loading) return;
    if (identity && onLoginPage) router.replace("/dashboard");
    if (!identity && !onLoginPage) router.replace("/login");
  }, [identity, loading, onLoginPage, router]);

  if (loading) return <Loading label="Checking your session…" />;
  if (!identity && !onLoginPage) {
    return <Loading label="Opening secure sign-in…" />;
  }
  if (identity && onLoginPage) {
    return <Loading label="Opening your dashboard…" />;
  }
  if (identity) return <>{children}</>;
  return <SignInScreen configured={configured} />;
}
