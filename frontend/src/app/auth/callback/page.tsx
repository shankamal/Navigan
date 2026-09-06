"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { completeSignIn } from "@/shared/auth/session";
import { ErrorNotice, Loading } from "@/shared/components/ui";
export default function Callback() {
  const router = useRouter();
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    let active = true;
    void completeSignIn()
      .then((user) => {
        const state: unknown = user.state;
        const returnTo =
          state &&
          typeof state === "object" &&
          "returnTo" in state &&
          typeof state.returnTo === "string" &&
          /^\/customers(?:\/CUS-[A-Za-z0-9-]+(?:\/edit)?|\/new)?$/.test(
            state.returnTo,
          )
            ? state.returnTo
            : "/customers";
        if (active) router.replace(returnTo);
      })
      .catch(() => {
        if (active)
          setError(
            new Error(
              "Sign-in could not be completed. Start a new sign-in request.",
            ),
          );
      });
    return () => {
      active = false;
    };
  }, [router]);
  return (
    <main className="callback-page">
      {error ? (
        <>
          <ErrorNotice error={error} />
          <Link href="/login" className="button button-primary">
            Return to sign-in
          </Link>
        </>
      ) : (
        <Loading label="Completing secure sign-in…" />
      )}
    </main>
  );
}
