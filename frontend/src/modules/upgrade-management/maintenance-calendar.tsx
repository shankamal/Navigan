"use client";
import { useEffect, useRef, useState } from "react";
import type {
  Cluster,
  EksUpgradePlan,
} from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import { ClusterContext } from "./cluster-context";
import { planScopes, scopeTypes, PlanScopeLabel } from "./plan-scope";
import { planStage } from "./component-plan-metrics";
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
  const [search, setSearch] = useState("");
  const [customer, setCustomer] = useState("all");
  const [environment, setEnvironment] = useState("all");
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");
  const customers = [
    ...new Map(
      rows.map((r) => [
        r.cluster.customerId,
        r.cluster.customerName ?? r.cluster.customerId,
      ]),
    ).entries(),
  ];
  const environments = [
    ...new Map(
      rows.map((r) => [
        r.cluster.environmentId,
        r.cluster.environmentName ?? r.cluster.environmentId,
      ]),
    ).entries(),
  ];
  const [view, setView] = useState<"month" | "week">("month");
  const weekRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (view === "week" && weekRef.current) weekRef.current.scrollTop = 8 * 48;
  }, [view]);
  const monday = new Date(selected + "T12:00:00");
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  const week = Array.from(
    { length: 7 },
    (_, i) =>
      new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i),
  );
  const days = calendarDays(month),
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone,
    events = rows.filter(
      (row) =>
        row.plan.scheduledFor &&
        Number.isFinite(new Date(row.plan.scheduledFor).getTime()) &&
        (customer === "all" || row.cluster.customerId === customer) &&
        (environment === "all" || row.cluster.environmentId === environment) &&
        (type === "all" || planScopes(row.plan).some((s) => s === type)) &&
        (status === "all" || planStage(row.plan, now) === status) &&
        [
          row.clusterName,
          row.cluster.customerName,
          row.plan.utilityEvidence?.label,
          row.plan.planId,
        ]
          .join(" ")
          .toLowerCase()
          .includes(search.toLowerCase()),
    ),
    selectedEvents = events.filter(
      (row) => dayKey(new Date(row.plan.scheduledFor!)) === selected,
    );
  function move(delta: number) {
    if (view === "week") {
      const next = new Date(selected + "T12:00:00");
      next.setDate(next.getDate() + delta * 7);
      setMonth(new Date(next.getFullYear(), next.getMonth(), 1));
      setSelected(dayKey(next));
      return;
    }
    const next = new Date(month.getFullYear(), month.getMonth() + delta, 1);
    setMonth(next);
    setSelected(dayKey(next));
  }
  return (
    <section className="upgrade-calendar" aria-label="Maintenance calendar">
      <header>
        <div>
          <h3>
            {view === "week"
              ? `Week of ${monday.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}`
              : month.toLocaleDateString(undefined, {
                  month: "long",
                  year: "numeric",
                })}
          </h3>
          <p>
            Requested starts · {zone}. Durations are not recorded. Awaiting
            approval is not confirmed.
          </p>
        </div>
        <div>
          <Button
            variant="secondary"
            aria-pressed={view === "month"}
            onClick={() => setView("month")}
          >
            Month
          </Button>
          <Button
            variant="secondary"
            aria-pressed={view === "week"}
            onClick={() => setView("week")}
          >
            Week
          </Button>
          <Button
            variant="secondary"
            aria-label={`Previous ${view}`}
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
            aria-label={`Next ${view}`}
            onClick={() => move(1)}
          >
            Next
          </Button>
        </div>
      </header>
      <div className="upgrade-centre-filters" aria-label="Calendar filters">
        <input
          aria-label="Search maintenance requests"
          placeholder="Search cluster or plan…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          aria-label="Calendar customer"
          value={customer}
          onChange={(e) => setCustomer(e.target.value)}
        >
          <option value="all">All customers</option>
          {customers.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="Calendar environment"
          value={environment}
          onChange={(e) => setEnvironment(e.target.value)}
        >
          <option value="all">All environments</option>
          {environments.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="Calendar upgrade type"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="all">All types</option>
          {scopeTypes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Calendar status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          {[
            "Draft",
            "Awaiting approval",
            "Approved",
            "Scheduled",
            "Running",
            "Overdue",
            "History",
          ].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
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
      <ul className="upgrade-stage-key">
        {["Draft", "Awaiting approval", "Scheduled", "Running", "Overdue"].map(
          (stage) => (
            <li key={stage}>
              <span className="upgrade-plan-status" data-status={stage}>
                {stage}
              </span>
            </li>
          ),
        )}
      </ul>
      {view === "month" ? (
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
              <div
                key={key}
                className={
                  "upgrade-calendar-day " +
                  (day.getMonth() !== month.getMonth() ? "outside-month" : "")
                }
              >
                <button
                  className="upgrade-calendar-date"
                  type="button"
                  aria-label={`${day.toLocaleDateString(undefined, { dateStyle: "full" })}, ${matches.length} maintenance requests`}
                  aria-pressed={key === selected}
                  onClick={() => setSelected(key)}
                >
                  <time dateTime={key}>{day.getDate()}</time>
                  {key === dayKey(new Date(now)) && <small>Today</small>}
                </button>
                {matches.slice(0, 2).map((row) => (
                  <button
                    type="button"
                    key={row.plan.planId}
                    className="upgrade-calendar-plan"
                    data-status={planStage(row.plan, now)}
                    onClick={() => onReview(row.plan.planId)}
                    title={row.clusterName + " · " + planStage(row.plan, now)}
                  >
                    <time>
                      {new Date(row.plan.scheduledFor!).toLocaleTimeString(
                        undefined,
                        { hour: "2-digit", minute: "2-digit" },
                      )}
                    </time>
                    <span>
                      {row.plan.kind === "UTILITY"
                        ? row.plan.utilityEvidence?.label + " · "
                        : ""}
                      {row.clusterName}
                    </span>
                  </button>
                ))}
                {matches.length > 2 && (
                  <button
                    className="upgrade-calendar-more"
                    onClick={() => setSelected(key)}
                  >
                    +{matches.length - 2} more
                  </button>
                )}
                {canCreate && onCreate && (
                  <button
                    type="button"
                    className="upgrade-calendar-add"
                    aria-label={`Create upgrade on ${key}`}
                    disabled={key < dayKey(new Date(now))}
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
      ) : (
        <div
          className="upgrade-week-scroll"
          ref={weekRef}
          aria-label="Weekly maintenance starts"
        >
          <div className="upgrade-week-grid">
            <div className="upgrade-week-hours">
              <strong>{zone}</strong>
              {Array.from({ length: 24 }, (_, hour) => (
                <span key={hour} style={{ top: 48 + hour * 48 }}>
                  {String(hour).padStart(2, "0")}:00
                </span>
              ))}
            </div>
            {week.map((day) => {
              const key = dayKey(day),
                matches = events.filter(
                  (row) => dayKey(new Date(row.plan.scheduledFor!)) === key,
                );
              return (
                <div className="upgrade-week-day" key={key}>
                  <header>
                    <button
                      aria-pressed={key === selected}
                      onClick={() => setSelected(key)}
                    >
                      {day.toLocaleDateString(undefined, {
                        weekday: "short",
                        day: "numeric",
                      })}
                      {key === dayKey(new Date(now)) ? " · Today" : ""}
                    </button>
                    {canCreate && onCreate && (
                      <button
                        aria-label={`Create upgrade on ${key}`}
                        disabled={key < dayKey(new Date(now))}
                        onClick={() => {
                          setSelected(key);
                          setCreateDate(key);
                        }}
                      >
                        +
                      </button>
                    )}
                  </header>
                  {Array.from({ length: 24 }, (_, hour) => (
                    <div
                      className="upgrade-week-hour"
                      key={hour}
                      aria-hidden="true"
                    />
                  ))}
                  {matches.map((row, index) => {
                    const date = new Date(row.plan.scheduledFor!);
                    const concurrent = matches.filter(
                      (r) =>
                        new Date(r.plan.scheduledFor!).getHours() ===
                        date.getHours(),
                    );
                    const lane = concurrent.findIndex(
                      (r) => r.plan.planId === row.plan.planId,
                    );
                    return (
                      <button
                        key={row.plan.planId}
                        className="upgrade-week-event"
                        title={`${row.clusterName} · ${row.plan.kind === "UTILITY" ? row.plan.utilityEvidence?.label : "Container upgrade"} · ${planStage(row.plan, now)}`}
                        data-status={planStage(row.plan, now)}
                        onClick={() => onReview(row.plan.planId)}
                        style={{
                          top:
                            48 +
                            (date.getHours() + date.getMinutes() / 60) * 48,
                          left: `${(lane / concurrent.length) * 100}%`,
                          width: `${100 / concurrent.length}%`,
                          zIndex: index + 1,
                        }}
                      >
                        <time>
                          {date.toLocaleTimeString(undefined, {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </time>
                        <strong>{row.clusterName}</strong>
                        <span>
                          {row.plan.kind === "UTILITY"
                            ? row.plan.utilityEvidence?.label
                            : "Container upgrade"}
                        </span>
                        <small>{planStage(row.plan, now)}</small>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}
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
                <PlanScopeLabel plan={row.plan} />
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
