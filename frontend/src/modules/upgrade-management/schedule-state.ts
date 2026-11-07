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

export function calendarSchedule(date?: string, now = new Date()): string {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return "";
  const selected = new Date(date + "T09:00:00");
  const candidate =
    selected.getTime() > now.getTime()
      ? selected
      : new Date(now.getTime() + 60 * 60 * 1000);
  if (
    candidate.getFullYear() !== Number(date.slice(0, 4)) ||
    candidate.getMonth() + 1 !== Number(date.slice(5, 7)) ||
    candidate.getDate() !== Number(date.slice(8, 10))
  )
    return "";
  return `${date}T${String(candidate.getHours()).padStart(2, "0")}:${String(candidate.getMinutes()).padStart(2, "0")}`;
}
