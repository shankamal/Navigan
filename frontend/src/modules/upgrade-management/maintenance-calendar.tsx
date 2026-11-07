"use client";
import { useState } from "react";
import type {
  Cluster,
  EksUpgradePlan,
} from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import { ClusterContext } from "./cluster-context";
import { scheduleOverdue } from "./schedule-state";
type Row = { clusterName: string; cluster: Cluster; plan: EksUpgradePlan };
export function dayKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
export function calendarDays(month: Date) {
  const start = new Date(month.getFullYear(), month.getMonth(), 1);
  start.setDate(1 - ((start.getDay() + 6) % 7));
  return Array.from(
    { length: 42 },
    (_, i) =>
      new Date(start.getFullYear(), start.getMonth(), start.getDate() + i),
  );
}
export function MaintenanceCalendar({
  rows,
  onReview,
  now,
  onCreate,
  canCreate = false,
}: {
  rows: Row[];
  onReview: (id: string) => void;
  now: number;
  onCreate?: (kind: "containers" | "utilities", date: string) => void;
  canCreate?: boolean;
}) {
  const [month, setMonth] = useState(
      () => new Date(new Date(now).getFullYear(), new Date(now).getMonth(), 1),
    ),
    [selected, setSelected] = useState(() => dayKey(new Date(now)));
  const [createDate, setCreateDate] = useState<string>();
  const days = calendarDays(month),
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone,
    events = rows.filter(
      (row) =>
        row.plan.scheduledFor &&
        Number.isFinite(new Date(row.plan.scheduledFor).getTime()),
    ),
    selectedEvents = events.filter(
      (row) => dayKey(new Date(row.plan.scheduledFor!)) === selected,
    );
  function move(delta: number) {
    const next = new Date(month.getFullYear(), month.getMonth() + delta, 1);
    setMonth(next);
    setSelected(dayKey(next));
  }
  return (
    <section className="upgrade-calendar" aria-label="Maintenance calendar">
      <header>
        <div>
          <h3>
            {month.toLocaleDateString(undefined, {
              month: "long",
              year: "numeric",
            })}
          </h3>
          <p>
            Requested maintenance starts · {zone}. Awaiting approval is not
            confirmed.
          </p>
        </div>
        <div>
          <Button
            variant="secondary"
            aria-label="Previous month"
            onClick={() => move(-1)}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              setMonth(
                new Date(
                  new Date(now).getFullYear(),
                  new Date(now).getMonth(),
                  1,
                ),
              );
              setSelected(dayKey(new Date(now)));
            }}
          >
            Today
          </Button>
          <Button
            variant="secondary"
            aria-label="Next month"
            onClick={() => move(1)}
          >
            Next
          </Button>
        </div>
      </header>
      {canCreate && createDate && (
        <div
          className="upgrade-calendar-create"
          role="group"
          aria-label="Create upgrade on selected date"
        >
          <div>
            <strong>
              New maintenance request ·{" "}
              {new Date(createDate + "T12:00:00").toLocaleDateString()}
            </strong>
            <p>
              Choose the upgrade type, then select a cluster and review
              readiness.
            </p>
          </div>
          <Button onClick={() => onCreate?.("containers", createDate)}>
            Container upgrade
          </Button>
          <Button
            variant="secondary"
            onClick={() => onCreate?.("utilities", createDate)}
          >
            Utility upgrade
          </Button>
          <Button variant="secondary" onClick={() => setCreateDate(undefined)}>
            Close
          </Button>
        </div>
      )}
      <div
        className="upgrade-calendar-grid"
        role="group"
        aria-label="Choose a maintenance date"
      >
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
          <strong className="calendar-weekday" key={day}>
            {day}
          </strong>
        ))}
        {days.map((day) => {
          const key = dayKey(day),
            matches = events.filter(
              (row) => dayKey(new Date(row.plan.scheduledFor!)) === key,
            );
          return (
            <div key={key} className="upgrade-calendar-day">
              <button
                type="button"
                aria-label={`${day.toLocaleDateString(undefined, { dateStyle: "full" })}, ${matches.length} maintenance requests`}
                aria-pressed={key === selected}
                className={
                  "upgrade-calendar-date " +
                  (day.getMonth() !== month.getMonth() ? "outside-month" : "")
                }
                onClick={() => setSelected(key)}
              >
                <time dateTime={key}>{day.getDate()}</time>
                {key === dayKey(new Date(now)) && <small>Today</small>}
                {matches.slice(0, 2).map((row) => (
                  <span
                    key={row.plan.planId}
                    className={
                      scheduleOverdue(row.plan, now)
                        ? "calendar-event overdue"
                        : "calendar-event"
                    }
                  >
                    {new Date(row.plan.scheduledFor!).toLocaleTimeString(
                      undefined,
                      { hour: "2-digit", minute: "2-digit" },
                    )}{" "}
                    · {row.clusterName}
                  </span>
                ))}
                {matches.length > 2 && (
                  <small>+{matches.length - 2} more</small>
                )}
              </button>
              {canCreate && onCreate && (
                <button
                  type="button"
                  className="upgrade-calendar-add"
                  aria-label={`Create upgrade on ${key}`}
                  disabled={key < dayKey(new Date(now))}
                  title={
                    key < dayKey(new Date(now))
                      ? "Choose today or a future date"
                      : "Create container or utility request"
                  }
                  onClick={() => {
                    setSelected(key);
                    setCreateDate(key);
                  }}
                >
                  +
                </button>
              )}
            </div>
          );
        })}
      </div>
      <section className="upgrade-calendar-agenda" aria-live="polite">
        <h3>
          Requests for{" "}
          {new Date(selected + "T12:00:00").toLocaleDateString(undefined, {
            dateStyle: "long",
          })}
        </h3>
        {!selectedEvents.length ? (
          <p>No maintenance starts requested for this date.</p>
        ) : (
          selectedEvents.map((row) => (
            <article key={row.plan.planId}>
              <div>
                <strong>
                  {row.clusterName} ·{" "}
                  {row.plan.kind === "UTILITY"
                    ? row.plan.utilityEvidence?.label
                    : "Container upgrade"}
                </strong>
                <p>
                  {new Date(row.plan.scheduledFor!).toLocaleTimeString()} ·{" "}
                  {scheduleOverdue(row.plan, now)
                    ? "Overdue · inactive"
                    : row.plan.status === "SUBMITTED"
                      ? "Awaiting approval"
                      : row.plan.status}{" "}
                  · {row.plan.currentVersion} → {row.plan.targetVersion}
                </p>
                <ClusterContext cluster={row.cluster} compact />
              </div>
              <Button
                variant="secondary"
                onClick={() => onReview(row.plan.planId)}
              >
                Review plan
              </Button>
            </article>
          ))
        )}
      </section>
    </section>
  );
}
