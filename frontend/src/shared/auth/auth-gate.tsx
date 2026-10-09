"use client";
import { useAuth } from "./auth-provider";
import { LoginForm } from "./login-form";
import { type ReactNode } from "react";
import { Cloud, Network } from "lucide-react";
import { Loading } from "@/shared/components/ui";
import "./login-workspace.css";

const clouds = [
  ["AWS", "amazonwebservices"],
  ["Azure", "microsoftazure"],
  ["Google Cloud", "googlecloud"],
  ["Oracle Cloud", "oracle"],
];
const containers = [
  ["Amazon EKS", "amazoneks"],
  ["Amazon ECS", "amazonecs"],
  ["Azure AKS", "microsoftazure"],
  ["Google GKE", "googlecloud"],
  ["Red Hat OpenShift", "redhatopenshift"],
  ["Kubernetes", "kubernetes"],
];
export function AuthGate({ children }: { children: ReactNode }) {
  const { identity, loading, configured } = useAuth();
  if (loading) return <Loading label="Checking your session…" />;
  if (identity) return <>{children}</>;
  return (
    <div className="signin-layout navigan-signin">
      <section
        className="signin-message login-introduction"
        aria-label="About Navigan"
      >
        <div className="login-product-brand">
          <Network size={35} aria-hidden="true" />
          <div>
            <strong>Navigan</strong>
            <span>Container Management Platform</span>
          </div>
        </div>
        <div className="login-hero-copy">
          <h1>
            One workspace.
            <br />
            Your cloud estate<span>.</span>
          </h1>
          <p>
            Unify, manage and scale your container environments across clouds —
            with clarity, control and confidence.
          </p>
        </div>
        <img
          className="login-estate-illustration"
          src="/graphics/login-cloud-estate.webp"
          alt=""
        />
        <section className="login-ecosystem" aria-label="Platform roadmap">
          <h2>Platform roadmap</h2>
          <div className="login-ecosystem-row">
            <h3>Clouds</h3>
            <ul>
              {clouds.map(([label, logo]) => (
                <li key={label}>
                  <img src={`/logos/${logo}.svg`} alt="" />
                  <span>{label}</span>
                </li>
              ))}
              <li>
                <Cloud size={22} aria-hidden="true" />
                <span>Other clouds</span>
              </li>
            </ul>
          </div>
          <div className="login-ecosystem-row">
            <h3>Containers</h3>
            <ul>
              {containers.map(([label, logo]) => (
                <li key={label}>
                  <img src={`/logos/${logo}.svg`} alt="" />
                  <span>{label}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </section>
      <section className="login-access-panel" aria-label="Secure sign-in">
        <div className="signin-card login-access-card">
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
        </div>
      </section>
    </div>
  );
}
