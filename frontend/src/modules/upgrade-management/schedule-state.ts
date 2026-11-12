"use client";
import { useEffect, useState } from "react";

type PlanSchedule = {
  status: string;
  scheduledFor?: string | null;
  planSpec?: {
    steps: {
      window: { scheduledFor: string; durationMinutes: number } | null;
    }[];
  };
  execution?: Record<string, unknown>;
};

export type ExecutionWindowState = {
  state: "UNSCHEDULED" | "UPCOMING" | "READY" | "EXPIRED";
  hopIndex: number;
  startsAt?: string;
  endsAt?: string;
};

export function executionWindowState(
  plan: PlanSchedule,
  now = Date.now(),
): ExecutionWindowState {
  const hopIndex = Number(plan.execution?.hopIndex ?? 0);
  if (!["APPROVED", "SCHEDULED"].includes(plan.status) || !plan.planSpec) {
    return { state: "UNSCHEDULED", hopIndex };
  }
  const window = plan.planSpec.steps[hopIndex]?.window;
  if (!window) return { state: "UNSCHEDULED", hopIndex };
  const start = new Date(window.scheduledFor).getTime();
  const end = start + window.durationMinutes * 60_000;
  if (!Number.isFinite(start)) {
    return { state: "UNSCHEDULED", hopIndex };
  }
  return {
    state: now < start ? "UPCOMING" : now >= end ? "EXPIRED" : "READY",
    hopIndex,
    startsAt: new Date(start).toISOString(),
    endsAt: new Date(end).toISOString(),
  };
}

export function scheduleOverdue(plan: PlanSchedule, now = Date.now()) {
  if (plan.planSpec && ["APPROVED", "SCHEDULED"].includes(plan.status)) {
    return executionWindowState(plan, now).state === "EXPIRED";
  }
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
