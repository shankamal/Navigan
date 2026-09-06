"use client";
import { useAuth } from "./auth-provider";
import { authManager } from "./session";
import { useState, type ReactNode } from "react";
import { LockKeyhole, ArrowUpRight } from "lucide-react";
import { Button, Loading, ErrorNotice } from "@/shared/components/ui";
export function AuthGate({ children }: { children: ReactNode }) {
  const { identity, loading, configured } = useAuth();
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState(false);
  if (loading) return <Loading label="Checking your session…" />;
  if (identity) return <>{children}</>;
  return (
    <div className="signin-layout">
      <div className="signin-message">
        <p className="eyebrow">NAVIGAN WORKSPACE</p>
        <h1>
          Your customers.
          <br />
          One connected platform.
        </h1>
        <p>
          Manage customer onboarding and approvals across your multi-cloud
          Kubernetes platform.
        </p>
        <div className="signin-capabilities">
          <span>Customer identity</span>
          <span>Cloud associations</span>
          <span>Governed approvals</span>
        </div>
      </div>
      <section className="signin-card">
        <div className="empty-icon">
          <LockKeyhole size={26} />
        </div>
        <h2>
          {configured
            ? "Sign in to your workspace"
            : "Connect your organization"}
        </h2>
        <p className="muted">
          {configured
            ? "Continue with your organization’s Cognito sign-in to access your authorized customers."
            : "An administrator needs to configure the Cognito app client before you can sign in."}
        </p>
        {error ? <ErrorNotice error={error} /> : null}
        <Button
          disabled={!configured || pending}
          onClick={() => {
            setError(undefined);
            setPending(true);
            void authManager()
              .signinRedirect({
                state: {
                  returnTo: window.location.pathname.startsWith("/customers")
                    ? window.location.pathname
                    : "/customers",
                },
              })
              .catch((e) => {
                setError(e);
                setPending(false);
              });
          }}
        >
          {pending ? "Opening sign-in…" : "Continue to sign in"}
          <ArrowUpRight size={18} />
        </Button>
        <p className="metadata">
          Access is based on your assigned role and customer scope.
        </p>
      </section>
    </div>
  );
}
