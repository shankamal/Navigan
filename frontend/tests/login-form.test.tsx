import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LoginForm } from "@/shared/auth/login-form";
import {
  signIn,
  confirmSignIn,
  resetPassword,
  confirmResetPassword,
} from "aws-amplify/auth";
vi.mock("aws-amplify/auth", () => ({
  signIn: vi.fn(),
  confirmSignIn: vi.fn(),
  resetPassword: vi.fn(),
  confirmResetPassword: vi.fn(),
}));
vi.mock("@/shared/auth/session", () => ({
  configureAuth: vi.fn(),
  authConfigured: true,
  accessToken: vi.fn(),
  clearSession: vi.fn(),
}));
const sms = {
  isSignedIn: false,
  nextStep: {
    signInStep: "CONFIRM_SIGN_IN_WITH_SMS_CODE",
    codeDeliveryDetails: { destination: "***1234", deliveryMedium: "SMS" },
  },
} as const;
function enter(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
function login() {
  enter("Email or username", "engineer@example.com");
  enter("Password", "test-password");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}
beforeEach(() => vi.resetAllMocks());
describe("Custom Cognito login", () => {
  it("uses SRP and completes an SMS challenge without redirecting to hosted login", async () => {
    vi.mocked(signIn).mockResolvedValue(sms);
    vi.mocked(confirmSignIn).mockRejectedValue(
      Object.assign(new Error(), { name: "CodeMismatchException" }),
    );
    render(<LoginForm />);
    login();
    await screen.findByLabelText("Verification code");
    expect(signIn).toHaveBeenCalledWith({
      username: "engineer@example.com",
      password: "test-password",
      options: { authFlowType: "USER_SRP_AUTH" },
    });
    enter("Verification code", "123456");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByText(
        "The verification code is incorrect. Please try again.",
      ),
    ).toBeInTheDocument();
    expect(confirmSignIn).toHaveBeenCalledWith({ challengeResponse: "123456" });
    expect(screen.getByLabelText("Verification code")).toBeInTheDocument();
  });
  it("requires matching new passwords and sends required first-login attributes", async () => {
    vi.mocked(signIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: {
        signInStep: "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED",
        missingAttributes: ["name"],
      },
    });
    vi.mocked(confirmSignIn).mockResolvedValue(sms);
    render(<LoginForm />);
    login();
    await screen.findByLabelText("New password");
    enter("New password", "New-Password123!");
    enter("Confirm new password", "different");
    enter("name", "Example User");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByText("The passwords do not match."),
    ).toBeInTheDocument();
    expect(confirmSignIn).not.toHaveBeenCalled();
    enter("Confirm new password", "New-Password123!");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByLabelText("Verification code");
    expect(confirmSignIn).toHaveBeenCalledWith({
      challengeResponse: "New-Password123!",
      options: { userAttributes: { name: "Example User" } },
    });
  });
  it("resets a forgotten password and returns to sign-in", async () => {
    vi.mocked(resetPassword).mockResolvedValue({
      isPasswordReset: false,
      nextStep: {
        resetPasswordStep: "CONFIRM_RESET_PASSWORD_WITH_CODE",
        codeDeliveryDetails: {
          destination: "e***@example.com",
          deliveryMedium: "EMAIL",
        },
      },
    });
    vi.mocked(confirmResetPassword).mockResolvedValue(undefined);
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    enter("Email or username", "engineer@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Send reset code" }));
    await screen.findByLabelText("New password");
    enter("New password", "New-Password123!");
    enter("Confirm new password", "New-Password123!");
    enter("Verification code", "654321");
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    await screen.findByText(
      "Your password has been reset. Sign in with your new password.",
    );
    expect(confirmResetPassword).toHaveBeenCalledWith({
      username: "engineer@example.com",
      confirmationCode: "654321",
      newPassword: "New-Password123!",
    });
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
  it("renders authenticator setup and clears setup secrets when going back", async () => {
    vi.mocked(signIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: {
        signInStep: "CONTINUE_SIGN_IN_WITH_TOTP_SETUP",
        totpSetupDetails: {
          sharedSecret: "TESTSETUPKEY",
          getSetupUri: () => new URL("otpauth://totp/test"),
        },
      },
    });
    render(<LoginForm />);
    login();
    await screen.findByText("TESTSETUPKEY");
    fireEvent.click(screen.getByRole("button", { name: "Back to sign-in" }));
    expect(screen.queryByText("TESTSETUPKEY")).not.toBeInTheDocument();
  });
  it("does not show raw SDK errors or credentials", async () => {
    vi.mocked(signIn).mockRejectedValue(new Error("secret request payload"));
    render(<LoginForm />);
    login();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(
      screen.queryByText("secret request payload"),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});
