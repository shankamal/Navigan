import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

export function PublicShell({ children }: { children: ReactNode }) {
  const logo = process.env.NEXT_PUBLIC_CORPORATE_LOGO_URL;
  return (
    <div className="public-shell">
      <header className="topbar">
        <Link href="/login" className="brand" aria-label="Navigan sign in">
          {logo && (
            <img src={logo} alt="Corporate logo" className="corporate-logo" />
          )}
          <span>Navigan</span>
        </Link>
        <span className="brand-divider" />
        <span className="platform-title">Container Management Platform</span>
        <div className="topbar-account">
          <ShieldCheck size={18} aria-hidden="true" />
          <span>Secure access</span>
        </div>
      </header>
      <main id="main-content" className="public-main">
        {children}
      </main>
    </div>
  );
}
