import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/shared/components/app-shell";
import { PublicShell } from "@/shared/components/public-shell";
import { architect, engineer } from "./fixtures";

const signOut = vi.fn();
let identity = engineer;

vi.mock("next/navigation", () => ({
  usePathname: () => "/customers",
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity, loading: false, configured: true }),
}));
vi.mock("@/shared/auth/session", () => ({
  signOut: () => signOut(),
}));

describe("Application shell permissions", () => {
  beforeEach(() => {
    identity = engineer;
    signOut.mockReset();
  });

  it("shows requester tools to a Cloud Engineer", () => {
    render(<AppShell>Content</AppShell>);
    expect(screen.getByText("Create Environment")).toBeInTheDocument();
    expect(screen.getByText("New Cluster Setup")).toBeInTheDocument();
    expect(screen.queryByText("Cluster Reviews")).not.toBeInTheDocument();
    expect(screen.queryByText("Sign out")).not.toBeInTheDocument();
  });

  it("shows review tools and hides create tools for a Platform Architect", () => {
    identity = architect;
    render(<AppShell>Content</AppShell>);
    expect(screen.queryByText("Create Environment")).not.toBeInTheDocument();
    expect(screen.queryByText("New Cluster Setup")).not.toBeInTheDocument();
    expect(screen.getByText("Cluster Reviews")).toBeInTheDocument();
    expect(screen.getByText("Bootstrap Approvals")).toBeInTheDocument();
  });

  it("places sign out inside the top-right account menu", () => {
    render(<AppShell>Content</AppShell>);
    fireEvent.click(
      screen.getByRole("button", { name: /Open account menu/i }),
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("renders the public shell without workspace navigation", () => {
    render(<PublicShell>Sign in form</PublicShell>);
    expect(screen.getByText("Sign in form")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Platform modules" }),
    ).not.toBeInTheDocument();
  });
});
