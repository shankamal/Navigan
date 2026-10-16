"use client";
import { useAuth } from "./auth-provider";
import { LoginForm } from "./login-form";
import { type ReactNode } from "react";
import Image from "next/image";
import { Cloud, LockKeyhole, ShieldCheck } from "lucide-react";
import { Loading } from "@/shared/components/ui";
import { NaviganMark } from "@/shared/components/navigan-mark";
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
          <NaviganMark />
          <div>
            <strong>Navigan</strong>
            <span>Your container command centre</span>
          </div>
        </div>
        <div className="login-hero-copy">
          <span className="login-introduction-eyebrow">CLOUD &amp; CONTAINER OPERATIONS</span>
          <h1>
            Navigate your cloud estate.
            <br />
            With confidence<span>.</span>
          </h1>
          <p>
            One connected workspace to discover, manage and modernize your
            container environments across clouds.
          </p>
        </div>
        <Image
          className="login-estate-illustration"
          src="/graphics/Deloitte-Maritime-Transparent.webp"
          alt="Maritime navigator connecting ships, ports and containers — illustrating Navigan's connected container ecosystem"
          width={1672}
          height={941}
          sizes="(max-width: 700px) 100vw, (max-width: 1050px) 50vw, 55vw"
          priority
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
          <div className="login-access-identity"><span><LockKeyhole size={15}/> SECURE WORKSPACE ACCESS</span><ShieldCheck size={20} aria-hidden="true"/></div>
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
