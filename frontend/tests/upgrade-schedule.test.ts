import { describe, expect, it } from "vitest";
import {
  executionWindowState,
  scheduleOverdue,
} from "../src/modules/upgrade-management/schedule-state";

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
  it("models approved execution windows as upcoming, ready and expired", () => {
    const plan = {
      status: "SCHEDULED",
      planSpec: {
        steps: [
          {
            window: {
              scheduledFor: time,
              durationMinutes: 120,
            },
          },
        ],
      },
      execution: {},
    };
    expect(
      executionWindowState(plan, Date.parse(time) - 1).state,
    ).toBe("UPCOMING");
    expect(executionWindowState(plan, Date.parse(time)).state).toBe("READY");
    expect(
      executionWindowState(plan, Date.parse(time) + 120 * 60_000 - 1).state,
    ).toBe("READY");
    expect(
      executionWindowState(plan, Date.parse(time) + 120 * 60_000).state,
    ).toBe("EXPIRED");
  });

  it("does not expire an approved start time or an unscheduled plan", () => {
    expect(
      scheduleOverdue(
        {
          status: "SCHEDULED",
          scheduledFor: time,
          planSpec: {
            steps: [
              {
                window: {
                  scheduledFor: time,
                  durationMinutes: 120,
                },
              },
            ],
          },
        },
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
