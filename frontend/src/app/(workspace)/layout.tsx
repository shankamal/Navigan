import { AppShell } from "@/shared/components/app-shell";
import { AuthGate } from "@/shared/auth/auth-gate";
export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGate>
      <AppShell>{children}</AppShell>
    </AuthGate>
  );
}
