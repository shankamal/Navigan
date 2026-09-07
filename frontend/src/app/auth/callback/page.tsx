import Link from "next/link";
export default function Callback() {
  return (
    <main className="callback-page">
      <h1>Sign in directly to Navigan</h1>
      <p>
        This sign-in link belongs to the previous login flow. Start a new
        session below.
      </p>
      <Link href="/login" className="button button-primary">
        Return to sign-in
      </Link>
    </main>
  );
}
