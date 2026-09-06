import { AppShell } from "@/shared/components/app-shell";
import { AuthGate } from "@/shared/auth/auth-gate";
import Link from "next/link";
export default function Login() {
  return (
    <AppShell>
      <AuthGate>
        <div className="empty-state">
          <h1>You’re signed in</h1>
          <Link className="button button-primary" href="/customers">
            Open customers
          </Link>
        </div>
      </AuthGate>
    </AppShell>
  );
}
