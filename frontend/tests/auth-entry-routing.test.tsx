import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Home from "@/app/page";
import { AuthGate } from "@/shared/auth/auth-gate";
import { useAuth } from "@/shared/auth/auth-provider";

const navigation = vi.hoisted(() => ({
  pathname: "/login",
  replace: vi.fn(),
  redirect: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ replace: navigation.replace }),
  redirect: navigation.redirect,
}));

vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: vi.fn(),
}));

vi.mock("@/shared/auth/login-form", () => ({
  LoginForm: () => <div>Sign-in form</div>,
}));

beforeEach(() => {
  vi.clearAllMocks();
  navigation.pathname = "/login";
  vi.mocked(useAuth).mockReturnValue({
    identity: null,
    loading: false,
    configured: true,
  });
});

describe("Navigan authentication entry routing", () => {
  it("routes the site root to the properly branded login page", () => {
    Home();
    expect(navigation.redirect).toHaveBeenCalledWith("/login");
  });

  it("displays the login splash only at /login for signed-out users", async () => {
    render(<AuthGate>Private workspace</AuthGate>);
    expect(
      await screen.findByRole("region", { name: "About Navigan" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Sign-in form")).toBeInTheDocument();
    expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("redirects signed-out users from protected pages without displaying an unbranded login form", async () => {
    navigation.pathname = "/dashboard";
    render(<AuthGate>Private workspace</AuthGate>);
    expect(screen.getByText("Opening secure sign-in…")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "About Navigan" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/login"),
    );
  });

  it("forwards signed-in users from /login to the dashboard", async () => {
    vi.mocked(useAuth).mockReturnValue({
      identity: {} as NonNullable<ReturnType<typeof useAuth>["identity"]>,
      loading: false,
      configured: true,
    });
    render(<AuthGate>Already signed in</AuthGate>);
    expect(screen.getByText("Opening your dashboard…")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "About Navigan" }),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/dashboard"),
    );
  });

  it("renders authenticated workspace content without navigation", () => {
    navigation.pathname = "/dashboard";
    vi.mocked(useAuth).mockReturnValue({
      identity: {} as NonNullable<ReturnType<typeof useAuth>["identity"]>,
      loading: false,
      configured: true,
    });
    render(<AuthGate>Private workspace</AuthGate>);
    expect(screen.getByText("Private workspace")).toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("waits for session resolution before redirecting", () => {
    navigation.pathname = "/dashboard";
    vi.mocked(useAuth).mockReturnValue({
      identity: null,
      loading: true,
      configured: true,
    });
    render(<AuthGate>Private workspace</AuthGate>);
    expect(screen.getByText("Checking your session…")).toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });
});
