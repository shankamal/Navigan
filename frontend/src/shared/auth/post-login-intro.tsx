"use client";
import { useEffect, useState, type ReactNode } from "react";
import { NaviganLifecycle } from "@/shared/components/navigan-lifecycle";
import { Loading } from "@/shared/components/ui";
import {
  clearPendingLifecycleIntro,
  hasPendingLifecycleIntro,
} from "./lifecycle-intro-state";

export function PostLoginIntro({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<boolean | null>(null);
  useEffect(() => {
    setPending(hasPendingLifecycleIntro());
  }, []);
  if (pending === null) return <Loading label="Opening your workspace…" />;
  if (!pending) return <>{children}</>;
  return (
    <main className="post-login-intro" aria-label="Welcome to Navigan">
      <NaviganLifecycle
        autoPlay
        onComplete={() => {
          clearPendingLifecycleIntro();
          setPending(false);
        }}
      />
    </main>
  );
}
