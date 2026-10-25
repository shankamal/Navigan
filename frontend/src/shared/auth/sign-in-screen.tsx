"use client";
import Image from "next/image";
import { LockKeyhole } from "lucide-react";
import { LoginForm } from "./login-form";
import "./login-workspace.css";

const platforms = [
  ["AWS", "amazonwebservices"],
  ["Azure", "microsoftazure"],
  ["Google Cloud", "googlecloud"],
  ["Red Hat", "redhatopenshift"],
  ["Kubernetes", "kubernetes"],
];

export function SignInScreen({ configured }: { configured: boolean }) {
  return (
    <div className="login-splash">
      <section className="login-story" aria-label="About Navigan">
        <div className="login-story-copy">
          <h1>
            Navigate your cloud.
            <br />
            <span>Simplify your operations.</span>
          </h1>
          <p>Manage with confidence. Migrate with clarity.</p>
        </div>
        <Image
          className="login-harbour"
          src="/graphics/navigan-royal-harbour.webp"
          alt="A royal navigator at the helm, guiding a container ship toward the harbour"
          width={1500}
          height={625}
          sizes="(max-width: 760px) 100vw, 60vw"
          preload
        />
        <ul
          className="login-platforms"
          aria-label="Cloud and container platforms"
        >
          {platforms.map(([label, logo]) => (
            <li key={label}>
              <img src={`/logos/${logo}.svg`} alt={label === "AWS" ? "AWS" : ""} width="20" height="18" />
              {label !== "AWS" && <span>{label}</span>}
            </li>
          ))}
        </ul>
      </section>
      <section className="login-panel" aria-label="Secure sign-in">
        <div className="login-panel-content">
          {configured ? (
            <LoginForm compactNotice />
          ) : (
            <div className="login-configuration">
              <h2>Connect your organization</h2>
              <p>
                An administrator needs to configure sign-in before you can
                continue.
              </p>
            </div>
          )}
          <div className="login-protection">
            <LockKeyhole size={22} aria-hidden="true" />
            <span>Protected enterprise access</span>
          </div>
        </div>
      </section>
    </div>
  );
}
