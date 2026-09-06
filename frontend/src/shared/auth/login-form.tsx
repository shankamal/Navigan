"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  signIn,
  confirmSignIn,
  resetPassword,
  confirmResetPassword,
  type SignInOutput,
} from "aws-amplify/auth";
import { configureAuth } from "./session";
import { Button, ErrorNotice } from "@/shared/components/ui";

type Step = SignInOutput["nextStep"];
type Mode = "login" | "forgot" | "reset" | "challenge";
export function loginError(error: unknown): Error {
  const name = error instanceof Error ? error.name : "";
  const messages: Record<string, string> = {
    NotAuthorizedException:
      "Sign-in was not accepted. Check your credentials, or ask your administrator to verify the public app client configuration.",
    UserNotFoundException: "Sign-in was not accepted. Check your credentials.",
    CodeMismatchException:
      "The verification code is incorrect. Please try again.",
    ExpiredCodeException:
      "This code has expired. Start again to request a new code.",
    InvalidPasswordException:
      "Your password does not meet your organization’s password policy.",
    PasswordHistoryPolicyViolationException:
      "Choose a password you have not used recently.",
    TooManyRequestsException:
      "Too many attempts. Wait a moment before trying again.",
    LimitExceededException:
      "Too many attempts. Wait before requesting another code.",
    UserUnconfirmedException:
      "Your account needs confirmation. Contact your administrator.",
    NetworkError:
      "Unable to connect. Check your internet connection and try again.",
  };
  return new Error(
    messages[name] ||
      "Sign-in could not be completed. Try again, or contact your administrator.",
  );
}
export function LoginForm() {
  const [mode, setMode] = useState<Mode>("login");
  const [step, setStep] = useState<Step>();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [answer, setAnswer] = useState("");
  const [attributes, setAttributes] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>();
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const lock = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const kind = step?.signInStep;
  const newPassword =
    mode === "reset" || kind === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED";
  const selection =
    kind === "CONTINUE_SIGN_IN_WITH_MFA_SELECTION" ||
    kind === "CONTINUE_SIGN_IN_WITH_MFA_SETUP_SELECTION";
  const emailSetup = kind === "CONTINUE_SIGN_IN_WITH_EMAIL_SETUP";
  const totp =
    step?.signInStep === "CONTINUE_SIGN_IN_WITH_TOTP_SETUP"
      ? step.totpSetupDetails
      : undefined;
  const missing =
    step?.signInStep === "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED"
      ? (step.missingAttributes ?? [])
      : [];
  const methods =
    step && "allowedMFATypes" in step ? (step.allowedMFATypes ?? []) : [];
  const delivery =
    step && "codeDeliveryDetails" in step
      ? step.codeDeliveryDetails?.destination
      : undefined;
  const title =
    mode === "login"
      ? "Sign in to your workspace"
      : mode === "forgot"
        ? "Reset your password"
        : newPassword
          ? "Choose a new password"
          : selection
            ? "Choose verification method"
            : totp
              ? "Set up your authenticator"
              : emailSetup
                ? "Set up email verification"
                : "Verify your sign-in";
  useEffect(() => {
    heading.current?.focus();
  }, [mode, kind]);
  function restart() {
    setMode("login");
    setStep(undefined);
    setPassword("");
    setConfirmation("");
    setAnswer("");
    setAttributes({});
    setError(undefined);
    setNotice("");
  }
  async function next(result: SignInOutput) {
    if (result.isSignedIn) {
      // A document navigation clears transient password/challenge state and restores the provider.
      const path = window.location.pathname;
      window.location.replace(
        /^\/customers(?:\/CUS-[A-Za-z0-9-]+(?:\/edit)?|\/new)?$/.test(path)
          ? path
          : "/customers",
      );
      return;
    }
    if (result.nextStep.signInStep === "RESET_PASSWORD") {
      setMode("forgot");
      setStep(undefined);
      setNotice("Reset your password to continue.");
      return;
    }
    if (result.nextStep.signInStep === "CONFIRM_SIGN_UP") {
      setError(
        new Error(
          "Your account needs confirmation. Contact your administrator.",
        ),
      );
      return;
    }
    const supported = [
      "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED",
      "CONFIRM_SIGN_IN_WITH_SMS_CODE",
      "CONFIRM_SIGN_IN_WITH_TOTP_CODE",
      "CONFIRM_SIGN_IN_WITH_EMAIL_CODE",
      "CONTINUE_SIGN_IN_WITH_TOTP_SETUP",
      "CONTINUE_SIGN_IN_WITH_EMAIL_SETUP",
      "CONTINUE_SIGN_IN_WITH_MFA_SELECTION",
      "CONTINUE_SIGN_IN_WITH_MFA_SETUP_SELECTION",
    ];
    if (!supported.includes(result.nextStep.signInStep)) {
      setError(
        new Error(
          "This account requires a sign-in method that is not enabled in Navigan. Contact your administrator.",
        ),
      );
      return;
    }
    setStep(result.nextStep);
    setMode("challenge");
    setAnswer("");
    setPassword("");
    setConfirmation("");
    setNotice("");
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (lock.current) return;
    if (newPassword && password !== confirmation) {
      setError(new Error("The passwords do not match."));
      return;
    }
    lock.current = true;
    setPending(true);
    setError(undefined);
    try {
      configureAuth();
      if (mode === "login") {
        await next(
          await signIn({
            username: username.trim(),
            password,
            options: { authFlowType: "USER_SRP_AUTH" },
          }),
        );
      } else if (mode === "forgot") {
        const result = await resetPassword({ username: username.trim() });
        if (
          result.nextStep.resetPasswordStep ===
          "CONFIRM_RESET_PASSWORD_WITH_CODE"
        ) {
          setMode("reset");
          setNotice(
            "If your account is eligible, a password reset code has been sent to your registered contact.",
          );
        } else {
          restart();
          setNotice("Password reset complete. Sign in with your new password.");
        }
      } else if (mode === "reset") {
        await confirmResetPassword({
          username: username.trim(),
          confirmationCode: answer.trim(),
          newPassword: password,
        });
        restart();
        setNotice(
          "Your password has been reset. Sign in with your new password.",
        );
      } else {
        await next(
          await confirmSignIn({
            challengeResponse: newPassword ? password : answer.trim(),
            ...(newPassword ? { options: { userAttributes: attributes } } : {}),
          }),
        );
      }
    } catch (e) {
      setError(loginError(e));
    } finally {
      setPassword("");
      setConfirmation("");
      setPending(false);
      lock.current = false;
    }
  }
  return (
    <form
      className="login-form"
      onSubmit={(event) => {
        void submit(event);
      }}
      aria-busy={pending}
    >
      <h2 ref={heading} tabIndex={-1}>
        {title}
      </h2>
      <p className="muted">
        {mode === "login"
          ? "Access your customers and cloud environments securely."
          : mode === "forgot"
            ? "Enter your account email or username to request a reset code."
            : delivery
              ? `Enter the code sent to ${delivery}.`
              : "Complete the step below to continue."}
      </p>
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      {error ? <ErrorNotice error={error} /> : null}
      <fieldset disabled={pending} className="unstyled-fieldset login-fields">
        {(mode === "login" || mode === "forgot") && (
          <label className="field">
            Email or username
            <input
              name="username"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoCapitalize="none"
              spellCheck={false}
            />
          </label>
        )}
        {totp && (
          <div className="totp-setup">
            <p>
              Add this setup key to your authenticator app, then enter its
              six-digit code. Keep the key private.
            </p>
            <code>{totp.sharedSecret}</code>
          </div>
        )}
        {(mode === "login" || newPassword) && (
          <label className="field">
            {newPassword ? "New password" : "Password"}
            <input
              name="password"
              type="password"
              autoComplete={newPassword ? "new-password" : "current-password"}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        )}
        {newPassword && (
          <label className="field">
            Confirm new password
            <input
              name="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
            />
          </label>
        )}
        {missing.map((attribute) => (
          <label className="field" key={attribute}>
            {attribute.replaceAll("_", " ")}
            <input
              required
              value={attributes[attribute] ?? ""}
              onChange={(e) =>
                setAttributes((current) => ({
                  ...current,
                  [attribute]: e.target.value,
                }))
              }
            />
          </label>
        ))}
        {selection ? (
          <label className="field">
            Verification method
            <select
              required
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
            >
              <option value="">Select a method</option>
              {methods.map((method) => (
                <option key={method} value={method}>
                  {method === "TOTP"
                    ? "Authenticator app"
                    : method === "SMS"
                      ? "Text message"
                      : "Email"}
                </option>
              ))}
            </select>
          </label>
        ) : (
          (mode === "reset" || (mode === "challenge" && !newPassword)) && (
            <label className="field">
              {emailSetup ? "Verification email" : "Verification code"}
              <input
                name="code"
                type={emailSetup ? "email" : "text"}
                inputMode={emailSetup ? "email" : "numeric"}
                autoComplete={emailSetup ? "email" : "one-time-code"}
                required
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              />
            </label>
          )
        )}
        <Button type="submit">
          {pending
            ? "Please wait…"
            : mode === "login"
              ? "Sign in"
              : mode === "forgot"
                ? "Send reset code"
                : mode === "reset"
                  ? "Reset password"
                  : "Continue"}
        </Button>
        {mode === "login" ? (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              restart();
              setMode("forgot");
            }}
          >
            Forgot password?
          </Button>
        ) : (
          <Button type="button" variant="ghost" onClick={restart}>
            Back to sign-in
          </Button>
        )}
      </fieldset>
      <p className="metadata">
        Access is based on your assigned role and customer permissions. Contact
        your administrator for an account.
      </p>
    </form>
  );
}
