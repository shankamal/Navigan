"use client";
import { useEffect, useState, type ReactNode } from "react";
import { loadRuntimeConfig } from "./runtime-config";
import { Button, Loading } from "@/shared/components/ui";

export function RuntimeConfigGate({ children }: { children: ReactNode }) {
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  useEffect(() => {
    let active = true;
    void loadRuntimeConfig().then(
      () => {
        if (active) setStatus("ready");
      },
      () => {
        if (active) setStatus("error");
      },
    );
    return () => {
      active = false;
    };
  }, [attempt]);
  if (status === "error") {
    return (
      <main className="panel" role="alert">
        <p>Unable to load application settings. Please try again.</p>
        <Button
          onClick={() => {
            setStatus("loading");
            setAttempt((value) => value + 1);
          }}
        >
          Retry
        </Button>
      </main>
    );
  }
  if (status !== "ready") return <Loading label="Opening your workspace…" />;
  return <>{children}</>;
}
