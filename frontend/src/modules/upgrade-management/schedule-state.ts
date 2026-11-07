"use client";
import { useEffect, useState } from "react";
export function scheduleOverdue(
  plan: { status: string; scheduledFor?: string | null },
  now = Date.now(),
) {
  return (
    ["DRAFT", "SUBMITTED"].includes(plan.status) &&
    Boolean(plan.scheduledFor) &&
    new Date(plan.scheduledFor!).getTime() <= now
  );
}
export function useScheduleClock() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}
