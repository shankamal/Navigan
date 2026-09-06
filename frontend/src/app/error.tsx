"use client";
import { Button } from "@/shared/components/ui";
export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="empty-state">
      <h1>We couldn’t load this view</h1>
      <p>Please try again. Your saved customer records are unchanged.</p>
      <Button onClick={reset}>Try again</Button>
    </main>
  );
}
