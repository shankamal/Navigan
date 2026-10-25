import Link from "next/link";
import type { ReactNode } from "react";
import "../auth/login-workspace.css";

export function PublicShell({ children }: { children: ReactNode }) {
  const logo = process.env.NEXT_PUBLIC_CORPORATE_LOGO_URL;
  return (
    <div className="public-shell login-public-shell">
      <header className="topbar">
        <Link href="/login" className="brand" aria-label="Navigan sign in">
          <img
            src={logo || "/logos/deloitte-reverse.svg"}
            alt="Deloitte"
            className="corporate-logo login-deloitte-logo"
          />
        </Link>
        <span className="brand-divider" />
        <span className="platform-title">Container Management Platform</span>
      </header>
      <main id="main-content" className="public-main">
        {children}
      </main>
      <footer className="login-public-footer">
        Navigan <span aria-hidden="true">·</span> Container Management Platform
      </footer>
    </div>
  );
}
