"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  Building2,
  Layers3,
  Boxes,
  ArrowRightLeft,
  PlugZap,
  Workflow,
  CircleArrowUp,
  Wrench,
  ArrowRight,
  RefreshCw,
  Plus,
} from "lucide-react";
import { IntentLink as Link } from "@/shared/components/intent-link";
import { useWorkspacePage } from "@/shared/components/workspace-page-context";
import { SummaryDonut } from "@/shared/components/summary-donut";
import { hasPermission } from "@/shared/auth/permissions";
import {
  activeMigration,
  openPlan,
  runtimeState,
  scheduledChanges,
  useDashboardData,
} from "./dashboard-data";
import styles from "./dashboard.module.css";

import {
  cloudColors as providerColors,
  healthColors,
} from "@/shared/components/chart-palette";
const providers = ["AWS", "AZURE", "GCP", "OCI"];
const providerLabels = ["AWS", "Azure", "GCP", "OCI"];
const states = ["Ready", "Degraded", "Paused", "Unverified"];

const label = (s: string) =>
  s
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (c) => c.toUpperCase());
const num = <T,>(items?: T[], predicate?: (item: T) => boolean) =>
  items ? (predicate ? items.filter(predicate).length : items.length) : "—";
function Badge({ children }: { children: ReactNode }) {
  return (
    <span className={styles.badge} data-tone={String(children).toLowerCase()}>
      {children}
    </span>
  );
}
function Panel({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.card} aria-label={title}>
      <header>
        <h2>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}
function Action({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link className={styles.action} href={href}>
      {children}
      <ArrowRight size={13} aria-hidden="true" />
    </Link>
  );
}
function Empty({ children }: { children: ReactNode }) {
  return <p className={styles.empty}>{children}</p>;
}

export function PlatformDashboard() {
  const d = useDashboardData();
  const { headerTarget } = useWorkspacePage();
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [days, setDays] = useState(7);
  const [now, setNow] = useState(() => Date.now());
  const [timezone, setTimezone] = useState("local time");
  useEffect(() => {
    setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone);
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const cs = d.customers,
    es = d.environments,
    fleet = d.fleet,
    ms = d.migrations;
  const plans = d.planRows.filter((r) => openPlan(r.plan));
  const upgradePlans = plans.filter((r) => r.plan.kind !== "UTILITY");
  const utilityPlans = plans.filter((r) => r.plan.kind === "UTILITY");
  const migrationUnavailable =
    d.scope.environmentId !== "all"
      ? "Environment-level migration totals unavailable"
      : "Data unavailable";
  const kpis = [
    {
      title: "Customers",
      value: num(cs, (c) => c.status === "ACTIVE"),
      suffix: "active",
      detail: cs
        ? `${cs.length} total · ${cs.filter((c) => ["SUBMITTED", "UNDER_REVIEW"].includes(c.status)).length} awaiting review`
        : "Data unavailable",
      icon: Building2,
      href: "/customers",
    },
    {
      title: "Environments",
      value: num(es, (e) => e.status === "ACTIVE"),
      suffix: "active",
      detail: es
        ? `${es.length} total · ${es.filter((e) => ["SUBMITTED", "UNDER_REVIEW"].includes(e.status)).length} awaiting review`
        : "Data unavailable",
      icon: Layers3,
      href: "/environments",
    },
    {
      title: "Clusters",
      value: num(fleet),
      suffix: "records",
      detail: fleet
        ? `${fleet.filter((c) => c.status === "ACTIVE").length} active records · ${fleet.filter((c) => c.status === "APPLYING").length} applying`
        : "Data unavailable",
      icon: Boxes,
      href: "/clusters",
    },
    {
      title: "Migrations",
      value: num(ms, (m) => activeMigration(m.status)),
      suffix: "active",
      detail: ms
        ? `${ms.filter((m) => /BLOCK|FAIL/.test(m.status)).length} blocked / failed · ${ms.filter((m) => m.status === "DRAFT").length} draft`
        : migrationUnavailable,
      icon: ArrowRightLeft,
      href: "/migrations",
    },
    {
      title: "Cluster Onboarding",
      value: "Planned",
      suffix: "",
      detail: "Workflow not available",
      icon: PlugZap,
      href: "/onboarding",
    },
    {
      title: "App Modernization",
      value: "Planned",
      suffix: "",
      detail: "Workflow not available",
      icon: Workflow,
      href: "/app-transformation",
    },
    {
      title: "Upgrades & Patching",
      value: d.plansComplete ? upgradePlans.length : "—",
      suffix: "open plans",
      detail: d.plansComplete
        ? `${upgradePlans.filter((r) => ["APPROVED", "SCHEDULED"].includes(r.plan.status)).length} approved / scheduled · ${upgradePlans.filter((r) => r.plan.status === "SUBMITTED").length} awaiting approval`
        : "Plan data incomplete or unavailable",
      icon: CircleArrowUp,
      href: "/upgrades",
    },
    {
      title: "System Utilities",
      value: d.plansComplete ? utilityPlans.length : "—",
      suffix: "open plans",
      detail: "Recorded utility plans · inventory below",
      icon: Wrench,
      href: "/upgrades/utilities",
    },
  ];
  const approvals = [
    ...(cs ?? [])
      .filter((c) => ["SUBMITTED", "UNDER_REVIEW"].includes(c.status))
      .map((c) => ({
        id: c.customerId,
        title: c.name,
        kind: "Customer",
        status: c.status,
        href: `/customers/${c.customerId}`,
      })),
    ...(es ?? [])
      .filter((e) => ["SUBMITTED", "UNDER_REVIEW"].includes(e.status))
      .map((e) => ({
        id: e.environmentId,
        title: e.environmentName,
        kind: "Environment",
        status: e.status,
        href: `/environments/${e.environmentId}`,
      })),
    ...(fleet ?? [])
      .filter((c) => ["SUBMITTED", "UNDER_REVIEW"].includes(c.status))
      .map((c) => ({
        id: c.clusterId,
        title: c.clusterName,
        kind: "Cluster",
        status: c.status,
        href: `/clusters/${c.clusterId}`,
      })),
    ...plans
      .filter((r) => r.plan.status === "SUBMITTED")
      .map((r) => ({
        id: r.plan.planId,
        title: r.cluster.clusterName,
        kind: r.plan.kind === "UTILITY" ? "Utility plan" : "Upgrade plan",
        status: r.plan.status,
        href: `/upgrades?plan=${encodeURIComponent(r.plan.planId)}`,
      })),
  ];
  const attention = [
    ...(fleet ?? [])
      .filter((c) => /FAILED/.test(c.status))
      .map((c) => ({
        id: c.clusterId,
        priority: "High",
        finding: "Cluster workflow failed",
        context: `${c.customerName ?? c.customerId} / ${c.clusterName}`,
        href: `/clusters/${c.clusterId}`,
        action: "Inspect workflow",
      })),
    ...(ms ?? [])
      .filter((m) => /BLOCK|FAIL/.test(m.status))
      .map((m) => ({
        id: m.migrationId,
        priority: "High",
        finding: `Migration ${label(m.status)}`,
        context: `${m.customerName} / ${m.name}`,
        href: `/migrations/${m.migrationId}`,
        action: "Review assessment",
      })),
    ...plans
      .filter((r) => r.plan.status === "FAILED")
      .map((r) => ({
        id: r.plan.planId,
        priority: "High",
        finding: "Change execution failed",
        context: `${r.cluster.customerName ?? r.cluster.customerId} / ${r.cluster.clusterName}`,
        href: `/upgrades?plan=${encodeURIComponent(r.plan.planId)}`,
        action: "Review plan",
      })),
    ...(fleet ?? [])
      .filter(
        (c) =>
          c.status === "ACTIVE" &&
          runtimeState(c, d.inventories.get(c.clusterId), now) === "Degraded",
      )
      .map((c) => ({
        id: `health-${c.clusterId}`,
        priority: "Medium",
        finding: "Runtime inventory reports degradation",
        context: `${c.customerName ?? c.customerId} / ${c.clusterName}`,
        href: `/clusters/${c.clusterId}`,
        action: "Inspect inventory",
      })),
  ];
  const environmentCounts = providers.map(
    (p) => es?.filter((e) => e.cloudProvider === p).length ?? 0,
  );
  const unmapped = es
    ? es.length - environmentCounts.reduce((a, b) => a + b, 0)
    : 0;
  const runtimeFleet = fleet?.filter((c) =>
    ["ACTIVE", "STOPPED", "BOOTSTRAPPING", "BOOTSTRAP_FAILED"].includes(
      c.status,
    ),
  );
  const healthCounts = states.map(
    (s) =>
      runtimeFleet?.filter(
        (c) => runtimeState(c, d.inventories.get(c.clusterId), now) === s,
      ).length ?? 0,
  );
  const schedule = scheduledChanges(d.planRows, days, now);
  const activeMigrations = (ms ?? []).filter((m) => activeMigration(m.status));
  const freshComponents = [...d.inventories.values()]
    .filter(
      (i) =>
        i?.runtimeInventory.expiresAt &&
        Date.parse(i.runtimeInventory.expiresAt) > now &&
        i.observedAt &&
        now - Date.parse(i.observedAt) <= 300000,
    )
    .flatMap((i) => i?.components ?? [])
    .filter(
      (c) =>
        c.observedAt &&
        Number.isFinite(Date.parse(c.observedAt)) &&
        Date.parse(c.observedAt) <= now &&
        now - Date.parse(c.observedAt) <= 300000,
    );
  const heading = (
    <div className={styles.heading}>
      <div>
        <h1>Platform Command Centre</h1>
        <p>Estate, delivery, and changes requiring attention</p>
      </div>
      <div className={styles.headingActions}>
        <span role="status" aria-live="polite">
          {d.refreshing
            ? "Refreshing…"
            : refreshFailed || d.errors
              ? "Some data unavailable"
              : d.updatedAt
                ? `Updated ${new Date(d.updatedAt).toLocaleTimeString("en-GB")}`
                : "Loading available data…"}
        </span>
        <button
          onClick={async () => {
            setRefreshFailed(false);
            setNow(Date.now());
            try {
              await d.refresh();
            } catch {
              setRefreshFailed(true);
            }
          }}
          disabled={d.refreshing}
        >
          <RefreshCw size={14} />
          Refresh
        </button>
        {hasPermission(d.identity, "environment.create") && (
          <Link className={styles.secondary} href="/environments/new">
            <Plus size={14} />
            New environment
          </Link>
        )}
        {hasPermission(d.identity, "cluster.create") && (
          <Link className={styles.primary} href="/clusters/new">
            <Plus size={14} />
            New cluster request
          </Link>
        )}
      </div>
    </div>
  );
  return (
    <div className={`${styles.dashboard} platform-dashboard command-dashboard`}>
      {headerTarget ? createPortal(heading, headerTarget) : heading}
      {d.errors > 0 && (
        <p className={styles.notice}>
          Some sources could not be loaded. Missing totals are shown as —;
          loaded records remain available.
        </p>
      )}
      <section className={styles.kpis} aria-label="Navigan platform KPIs">
        {kpis.map((k) => (
          <Link key={k.title} href={k.href} className={styles.kpi}>
            <k.icon size={19} />
            <div>
              <h2>{k.title}</h2>
              <strong>
                {k.value}
                {typeof k.value === "number" && <small> {k.suffix}</small>}
              </strong>
              <p>{k.detail}</p>
            </div>
          </Link>
        ))}
      </section>
      <div className={styles.columns}>
        <div className={styles.mainColumn}>
          <Panel title="Requires attention">
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th>Priority</th>
                    <th>Finding</th>
                    <th>Customer / cluster</th>
                    <th>Next action</th>
                  </tr>
                </thead>
                <tbody>
                  {attention.slice(0, 5).map((a) => (
                    <tr key={a.id}>
                      <td>
                        <Badge>{a.priority}</Badge>
                      </td>
                      <td>{a.finding}</td>
                      <td>{a.context}</td>
                      <td>
                        <Action href={a.href}>{a.action}</Action>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!attention.length && (
              <Empty>
                {d.pending
                  ? "Loading recorded findings…"
                  : d.errors
                    ? "No findings in loaded sources; some sources are unavailable."
                    : "No blocking findings in loaded records. Unverified telemetry is not a health pass."}
              </Empty>
            )}
          </Panel>
          <Panel
            title="Cluster & environment landscape"
            action={<Action href="/clusters">View all</Action>}
          >
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th>Cluster</th>
                    <th>Customer / environment</th>
                    <th>Version</th>
                    <th>Nodes</th>
                    <th>Health</th>
                    <th>Next action</th>
                  </tr>
                </thead>
                <tbody>
                  {(fleet ?? []).slice(0, 5).map((c) => {
                    const i = d.inventories.get(c.clusterId);
                    const state = runtimeState(c, i, now);
                    const nodes = i?.runtimeInventory.resources.filter(
                      (r) => r.kind === "Node",
                    );
                    const freshNodes =
                      i?.runtimeInventory.expiresAt &&
                      Date.parse(i.runtimeInventory.expiresAt) > now &&
                      i.runtimeInventory.observedAt &&
                      now - Date.parse(i.runtimeInventory.observedAt) <= 300000;
                    return (
                      <tr key={c.clusterId}>
                        <td>
                          {c.clusterName}
                          <small>{label(c.status)}</small>
                        </td>
                        <td>
                          {c.customerName ?? c.customerId}
                          <small>{c.environmentName ?? c.environmentId}</small>
                        </td>
                        <td>
                          {String(c.configuration?.kubernetesVersion ?? "—")}
                        </td>
                        <td>
                          {state !== "Unverified" && freshNodes && nodes
                            ? `${nodes.filter((n) => n.ready > 0).length}/${i?.runtimeInventory.metrics.nodeCount ?? nodes.length}`
                            : "—"}
                        </td>
                        <td>
                          <Badge>{state}</Badge>
                        </td>
                        <td>
                          <Action href={`/clusters/${c.clusterId}`}>
                            View cluster
                          </Action>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!fleet?.length && (
              <Empty>
                {fleet
                  ? "No clusters in the selected scope."
                  : "Cluster inventory unavailable."}
              </Empty>
            )}
            <p className={styles.note}>
              Showing {Math.min(fleet?.length ?? 0, 5)} of{" "}
              {fleet?.length ?? "—"} records. Health requires fresh runtime
              evidence.
            </p>
          </Panel>
        </div>
        <div className={styles.sideColumn}>
          <Panel title="Cloud distribution">
            {es?.length ? (
              <>
                <div className={styles.chart}>
                  <SummaryDonut
                    label="Environment profiles by cloud provider"
                    total={es.length}
                    center={String(es.length)}
                    caption="environments"
                    values={[...environmentCounts, unmapped]}
                    colors={[...providerColors, "#CBD2D9"]}
                  />
                  <ul>
                    {[
                      ...providerLabels,
                      ...(unmapped ? ["Other / unverified"] : []),
                    ].map((p, i) => (
                      <li key={p}>
                        <i
                          style={{
                            background: [...providerColors, "#CBD2D9"][i],
                          }}
                        />
                        {p}
                        <strong>{[...environmentCounts, unmapped][i]}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
                <p className={styles.note}>
                  All environment profiles in the selected scope.
                </p>
              </>
            ) : (
              <Empty>
                {es
                  ? "No environments in this scope."
                  : "Cloud distribution unavailable."}
              </Empty>
            )}
          </Panel>
          <Panel title="Estate health">
            {runtimeFleet?.length ? (
              <>
                <div className={styles.chart}>
                  <SummaryDonut
                    label="Estate health from runtime evidence"
                    total={runtimeFleet.length}
                    center={String(runtimeFleet.length)}
                    caption="clusters"
                    values={healthCounts}
                    colors={healthColors}
                  />
                  <ul>
                    {states.map((s, i) => (
                      <li key={s}>
                        <i style={{ background: healthColors[i] }} />
                        {s}
                        <strong>{healthCounts[i]}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
                <p className={styles.note}>
                  Provisioned records only. Stale telemetry is Unverified;
                  stopped or verified zero-node clusters are Paused.
                </p>
              </>
            ) : (
              <Empty>
                {fleet
                  ? "No provisioned cluster records in this scope."
                  : "Health inventory unavailable."}
              </Empty>
            )}
          </Panel>
        </div>
      </div>
      <div className={styles.twoColumns}>
        <Panel
          title="Pending approvals"
          action={<Action href="/my-work">My Work</Action>}
        >
          <p className={styles.approvalCount}>
            {approvals.length} recorded
            {(!cs || !es || !fleet || !d.plansComplete) &&
              " · partial coverage"}
          </p>
          {approvals.slice(0, 4).map((a) => (
            <div className={styles.listRow} key={a.id}>
              <div>
                <strong>{a.title}</strong>
                <small>
                  {a.kind} · {label(a.status)}
                </small>
              </div>
              <Action href={a.href}>View request</Action>
            </div>
          ))}
          {!approvals.length && (
            <Empty>No pending requests in the loaded sources.</Empty>
          )}
        </Panel>
        <Panel
          title="Migrations in progress"
          action={<Action href="/migrations">View all</Action>}
        >
          {activeMigrations.slice(0, 4).map((m) => (
            <div className={styles.listRow} key={m.migrationId}>
              <div>
                <strong>{m.name}</strong>
                <small>{m.customerName}</small>
              </div>
              <Action href={`/migrations/${m.migrationId}`}>
                {label(m.status)}
              </Action>
            </div>
          ))}
          {!activeMigrations.length && (
            <Empty>
              {ms
                ? "No active migration assessments in this scope."
                : migrationUnavailable}
            </Empty>
          )}
        </Panel>
      </div>
      <Panel
        title="Upcoming Maintenance & Changes"
        action={
          <div className={styles.scheduleActions}>
            <select
              aria-label="Maintenance horizon"
              value={days}
              onChange={(e) => {
                setDays(Number(e.target.value));
                setNow(Date.now());
              }}
            >
              <option value={7}>Next 7 days</option>
              <option value={30}>Next 30 days</option>
            </select>
            <Action href="/upgrades?tab=schedule">
              View maintenance calendar
            </Action>
          </div>
        }
      >
        <div className={styles.tableScroll}>
          <table>
            <thead>
              <tr>
                <th>Change</th>
                <th>Customer / environment</th>
                <th>Cluster / application</th>
                <th>Scheduled window</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {schedule.slice(0, 5).map((r) => (
                <tr key={`${r.plan.planId}-${r.scheduledFor}-${r.step}`}>
                  <td>
                    <Link
                      href={`/upgrades?plan=${encodeURIComponent(r.plan.planId)}`}
                    >
                      {r.plan.kind === "UTILITY"
                        ? `${r.plan.utilityEvidence?.label ?? "Utility"} upgrade`
                        : `${label(r.plan.planSpec?.scope ?? "CLUSTER")} upgrade`}
                      {r.step ? ` · stage ${r.step}` : ""}
                    </Link>
                  </td>
                  <td>
                    {r.cluster.customerName ?? r.cluster.customerId}
                    <small>
                      {r.cluster.environmentName ?? r.cluster.environmentId}
                    </small>
                  </td>
                  <td>{r.cluster.clusterName}</td>
                  <td>
                    {new Date(r.scheduledFor).toLocaleString(undefined, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                    {r.durationMinutes ? ` · ${r.durationMinutes} min` : ""}
                  </td>
                  <td>
                    <Badge>{label(r.plan.status)}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!schedule.length && (
          <Empty>
            {d.plansComplete
              ? `No recorded changes scheduled in the next ${days} days.`
              : "Schedule data is incomplete or unavailable."}
          </Empty>
        )}
        <p className={styles.note}>
          Times use your browser timezone ({timezone}). Up to 5 recorded plan
          windows; approvals and execution gates remain enforced. Environment,
          migration and standalone patch schedules are not exposed by the
          current APIs.
        </p>
      </Panel>
      <p className={styles.note}>
        System utilities:{" "}
        {d.inventoriesComplete
          ? `${freshComponents.length} components with recent inventory; ${freshComponents.filter((c) => ["DEGRADED", "MISSING"].includes(c.status)).length} require review.`
          : "Component inventory incomplete or unavailable."}{" "}
        Cluster onboarding and application modernization remain planned
        capabilities.
      </p>
    </div>
  );
}
