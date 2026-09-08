"use client";
import { useAuth } from "./auth-provider";
import { LoginForm } from "./login-form";
import { type ReactNode } from "react";
import { LockKeyhole } from "lucide-react";
import { Loading } from "@/shared/components/ui";
export function AuthGate({ children }: { children: ReactNode }) {
  const { identity, loading, configured } = useAuth();
  if (loading) return <Loading label="Checking your session…" />;
  if (identity) return <>{children}</>;
  return (
    <div className="signin-layout">
      <div className="signin-message">
        <p className="eyebrow">NAVIGAN WORKSPACE</p>
        <h1>
          Accelerate Kubernetes adoption.
          <br />
          Empower application teams.
        </h1>
        <p>
          Navigan enables self-service Kubernetes provisioning with consistent
          standards and governance. By abstracting infrastructure complexity, it
          empowers application teams to onboard seamlessly and accelerate
          migration to Kubernetes—with greater autonomy and less reliance on
          cloud teams.
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
        {configured ? (
          <LoginForm />
        ) : (
          <>
            <h2>Connect your organization</h2>
            <p>
              An administrator needs to configure sign-in before you can
              continue.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
