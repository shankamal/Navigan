import Link from "next/link";
export default function NotFound() {
  return (
    <main className="empty-state">
      <h1>Page not found</h1>
      <Link href="/customers" className="button button-primary">
        Back to customers
      </Link>
    </main>
  );
}
