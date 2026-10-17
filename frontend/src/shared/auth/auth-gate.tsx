"use client";
import { useAuth } from "./auth-provider";
import { LoginForm } from "./login-form";
import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
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
            <span>Container Management Platform</span>
          </div>
        </div>
        <div className="login-hero-copy">
          <h1>
            Navigate your container cloud estate.
            <br />
            With confidence.
          </h1>
          <h2 className="login-hero-tagline">Manage today. Modernize tomorrow.</h2>
          <p>
            Discover, manage and assess container environments across clouds,
            with intelligent insights and migration planning—all from one secure workspace.
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
        <section className="login-ecosystem" aria-label="Cloud and container platform coverage">
          <div className="login-ecosystem-row">
            <h3>Cloud platforms</h3>
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
            <h3>Container platforms</h3>
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
          <div className="login-access-security"><LockKeyhole size={20} aria-hidden="true"/><div><strong>Protected enterprise access</strong><span>Secure authentication for your Navigan workspace.</span></div><ShieldCheck size={17} aria-hidden="true"/></div>
        </div>
      </section>
    </div>
  );
}
