import { describe, expect, it } from "vitest";
import { scheduleOverdue } from "../src/modules/upgrade-management/schedule-state";

describe("requested maintenance schedule validity", () => {
  const time = "2026-11-07T02:45:00Z";
  it("marks a pending schedule inactive at its requested start", () => {
    expect(
      scheduleOverdue(
        { status: "SUBMITTED", scheduledFor: time },
        Date.parse(time) - 1,
      ),
    ).toBe(false);
    expect(
      scheduleOverdue(
        { status: "SUBMITTED", scheduledFor: time },
        Date.parse(time),
      ),
    ).toBe(true);
    expect(
      scheduleOverdue(
        { status: "DRAFT", scheduledFor: time },
        Date.parse(time) + 1,
      ),
    ).toBe(true);
  });
  it("does not expire an approved start time or an unscheduled plan", () => {
    expect(
      scheduleOverdue(
        { status: "SCHEDULED", scheduledFor: time },
        Date.parse(time) + 1,
      ),
    ).toBe(false);
    expect(
      scheduleOverdue(
        { status: "EXECUTING", scheduledFor: time },
        Date.parse(time) + 1,
      ),
    ).toBe(false);
    expect(scheduleOverdue({ status: "SUBMITTED" }, Date.parse(time))).toBe(
      false,
    );
  });
});
