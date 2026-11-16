"use client";

import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  Monitor,
  RefreshCw,
  Search,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { Button } from "@/shared/components/ui";
import { useOptionalWorkspaceScope } from "@/shared/components/workspace-scope-context";
import { useUpgradePlans } from "./upgrade-plan-data";
import { UtilityInventory } from "./live-upgrade-inventory";
import { useScheduleClock } from "./schedule-state";
import { utilityCatalogue, utilityRows } from "./utility-catalogue";
import { falcoHealthEvidence } from "./utility-health-evidence";
import { activeUtilityPlan } from "./utility-plan-actions";
import "./system-utilities.css";

const views = [
  "Installed utilities",
  "Catalogue",
  "Change plans",
  "Maintenance & history",
] as const;
type View = (typeof views)[number];

export function SystemUtilitiesWorkspace({
  onReview,
  requestedDate,
}: {
  onReview: (id: string | null, reschedule?: boolean) => void;
  requestedDate?: string;
}) {
  const data = useUpgradePlans();
  const { identity } = useAuth();
  const scope = useOptionalWorkspaceScope();
  const now = useScheduleClock();
  const [view, setView] = useState<View>("Installed utilities");
  const [clusterId, setClusterId] = useState("");
  const [planning, setPlanning] = useState<string | null>(
    requestedDate ? "headlamp" : null,
  );
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [catalogueCode, setCatalogueCode] = useState<string>("headlamp");
  const fleet = data.fleet.filter(
    (item) =>
      item.status === "ACTIVE" &&
      (!scope ||
        scope.customerId === "all" ||
        item.customerId === scope.customerId) &&
      (!scope ||
        scope.environmentId === "all" ||
        item.environmentId === scope.environmentId),
  );
  const selected =
    fleet.find((item) => item.clusterId === clusterId) ?? fleet[0];
  const selectedId = selected?.clusterId ?? "";
  const inventory = useQuery({
    queryKey: [
      "upgrade-utility-inventory",
      identity?.subject,
      identity?.authorizationRevision,
      selectedId,
    ],
    queryFn: () => clusters.platformComponents(selectedId),
    enabled: Boolean(selectedId),
    retry: false,
    staleTime: 30_000,
  });
  const rows = utilityRows(inventory.data?.components ?? [], now);
  const supportedRows = rows.filter((row) => row.planning && row.reported);
  const releaseQueries = useQueries({
    queries: supportedRows.map((row) => ({
      queryKey: [
        "utility-upgrade-options",
        identity?.subject,
        identity?.authorizationRevision,
        selectedId,
        row.code,
        row.version,
      ],
      queryFn: () => clusters.utilityUpgradeOptions(selectedId, row.code),
      enabled: Boolean(selectedId) && !inventory.isError,
      staleTime: 60_000,
      retry: false,
    })),
  });
  const releasesFor = (code: string) =>
    releaseQueries[supportedRows.findIndex((row) => row.code === code)];
  const upToDateFor = (code: string) => {
    const query = releasesFor(code);
    return (
      query &&
      !query.isError &&
      !query.isFetching &&
      query.data?.releaseStatus === "UP_TO_DATE"
    );
  };
  const state = data.stateForCluster(selectedId);
  const plans = data.rows
    .filter(
      (row) => row.plan.kind === "UTILITY" && row.plan.clusterId === selectedId,
    )
    .map((row) => row.plan);
  const pending = state.pending;
  const visiblePlans =
    view === "Change plans"
      ? plans.filter((plan) =>
          ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
            plan.status,
          ),
        )
      : [...plans].sort(
          (a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt),
        );
  const count =
    pending || state.error
      ? "—"
      : String(plans.filter((plan) => plan.status === "SUBMITTED").length);
  const entry =
    utilityCatalogue.find((item) => item.code === catalogueCode) ??
    utilityCatalogue[0];
  const selectedUtility = rows.find((row) => row.code === entry.code);
  const canPlan = hasPermission(identity, "cluster.upgrade.plan");
  const visibleRows = rows.filter((row) =>
    `${row.name} ${row.category}`.toLowerCase().includes(search.toLowerCase()),
  );
  const catalog = utilityCatalogue.filter(
    (item) =>
      (category === "All" || item.category === category) &&
      `${item.name} ${item.description}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const scheduled = plans
    .filter(
      (plan) =>
        plan.scheduledFor &&
        ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
          plan.status,
        ),
    )
    .sort((a, b) => Date.parse(a.scheduledFor!) - Date.parse(b.scheduledFor!));
  const formatTime = (time?: string | null) =>
    time && Number.isFinite(Date.parse(time))
      ? new Date(time).toLocaleString()
      : "Not reported";

  const upgradeAction = (
    code: string,
    reported: boolean,
    supported: boolean,
  ) => {
    const active = activeUtilityPlan(plans, selectedId, code);
    if (active)
      return (
        <Button onClick={() => onReview(active.planId)}>Review plan</Button>
      );
    if (!supported)
      return (
        <span className="utility-secondary">Upgrade not available yet</span>
      );
    if (pending || state.error)
      return (
        <Button disabled>
          {pending ? "Checking plans…" : "Plans unavailable"}
        </Button>
      );
    if (upToDateFor(code))
      return (
        <span className="utility-secondary">Up to date — no action needed</span>
      );
    return (
      <Button
        disabled={!canPlan || !reported}
        onClick={() => setPlanning(code)}
      >
        Plan upgrade
      </Button>
    );
  };

  if (planning && selected)
    return (
      <div className="utility-planning-screen">
        <UtilityInventory
          key={`${selectedId}-${planning}`}
          initialCode={planning}
          requestedDate={requestedDate}
          onCancel={() => setPlanning(null)}
          fleet={fleet}
          selected={selected}
          selectedId={selectedId}
          onSelect={(value) => {
            setClusterId(value);
          }}
          onReview={(id) => {
            setPlanning(null);
            onReview(id);
          }}
        />
      </div>
    );

  return (
    <section
      className="system-utilities"
      aria-label="System utility management"
    >
      <div className="utility-view-row">
        <nav aria-label="System utility views" className="utility-views">
          {views.map((label) => (
            <button
              key={label}
              type="button"
              aria-current={view === label ? "page" : undefined}
              onClick={() => {
                setView(label);
                setSearch("");
              }}
            >
              {label}
            </button>
          ))}
        </nav>
        <Button
          variant="secondary"
          onClick={() => {
            setView("Catalogue");
            setSearch("");
          }}
        >
          Browse catalogue
        </Button>
      </div>
      <div className="utility-context-row">
        <label>
          Managed cluster{" "}
          <select
            aria-label="Utility cluster"
            value={selectedId}
            onChange={(event) => setClusterId(event.target.value)}
          >
            {!fleet.length && (
              <option value="">
                {data.pending
                  ? "Loading clusters…"
                  : "No active cluster in scope"}
              </option>
            )}
            {fleet.map((item) => (
              <option key={item.clusterId} value={item.clusterId}>
                {item.clusterName}
              </option>
            ))}
          </select>
        </label>
        <span>
          {selected?.platform ?? "—"} ·{" "}
          {selected?.environmentName ?? "Environment not reported"}
        </span>
        <span>Observed {formatTime(inventory.data?.observedAt)}</span>
        <Button
          variant="secondary"
          disabled={inventory.isFetching || !selectedId}
          onClick={() => {
            void inventory.refetch();
            data.refresh();
          }}
        >
          <RefreshCw size={14} /> Refresh utilities
        </Button>
      </div>
      {data.errors.length > 0 && (
        <p role="alert">
          Some cluster plans could not be loaded. Counts may be unavailable.{" "}
          {data.errors.join(" · ")}
        </p>
      )}
      {selectedId && inventory.isError && (
        <p role="alert">
          Utility inventory could not be loaded. {inventory.error.message}
        </p>
      )}
      {view === "Installed utilities" && (
        <>
          <div className="utility-metrics">
            {[
              [
                "Utilities tracked",
                inventory.isPending || inventory.isError ? "—" : rows.length,
                "Includes required utilities not reporting",
              ],
              [
                "Chart versions reported",
                inventory.isPending || inventory.isError
                  ? "—"
                  : rows.filter((row) => row.reported).length,
                "Chart packages, including the shared monitoring stack",
              ],
              [
                "Healthy and synced",
                inventory.isPending || inventory.isError
                  ? "—"
                  : rows.filter((row) => row.healthy).length,
                "Based on observations within 15 minutes",
              ],
              [
                "Awaiting approval",
                count,
                "Submitted utility plans in this cluster",
              ],
            ].map(([label, value, hint]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
                <small>{hint}</small>
              </div>
            ))}
          </div>
          <section
            className="utility-table-surface"
            aria-labelledby="installed-utility-title"
          >
            <header>
              <h2 id="installed-utility-title">Installed utilities</h2>
              <span>
                Chart and application versions are tracked separately.
              </span>
            </header>
            <label className="utility-search">
              <Search size={15} />
              <input
                aria-label="Search installed utilities"
                placeholder="Search utilities or category"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <div className="utility-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Utility</th>
                    <th>Category</th>
                    <th>Chart version</th>
                    <th>Application version</th>
                    <th>Health</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
                    <tr key={row.code}>
                      <td>
                        <div className="utility-name">
                          <Monitor size={17} />
                          <div>
                            <strong>{row.name}</strong>
                            {row.code === "grafana" && (
                              <small>Grafana + Prometheus</small>
                            )}
                          </div>
                        </div>
                      </td>
                      <td>{row.category}</td>
                      <td>{row.version}</td>
                      <td>
                        <span className="utility-secondary">Not reported</span>
                      </td>
                      <td>
                        <span
                          className={`utility-health ${row.healthy ? "healthy" : row.status === "Degraded" ? "degraded" : "unknown"}`}
                        >
                          {row.status}
                        </span>
                        {row.code === "falco" && !row.healthy && (
                          <details className="utility-health-details">
                            <summary>Why this status?</summary>
                            <p>
                              Argo CD:{" "}
                              {inventory.data?.components.find(
                                (item) =>
                                  item.componentCode.toLowerCase() === "falco",
                              )?.healthStatus ?? "Not reported"}
                              . Navigan does not mark this healthy without
                              supporting evidence.
                            </p>
                            <ul>
                              {falcoHealthEvidence(inventory.data, now).map(
                                (message, index) => (
                                  <li key={index}>{message}</li>
                                ),
                              )}
                            </ul>
                          </details>
                        )}
                      </td>
                      <td>
                        {upgradeAction(row.code, row.reported, row.planning)}
                      </td>
                    </tr>
                  ))}
                  {!visibleRows.length && (
                    <tr>
                      <td colSpan={6}>
                        {!selectedId
                          ? data.pending
                            ? "Loading managed cluster inventory…"
                            : "No active managed clusters are available in this workspace scope."
                          : inventory.isPending
                            ? "Loading installed utilities…"
                            : inventory.isError
                              ? "Inventory unavailable. Refresh to retry."
                              : rows.length
                                ? "No utilities match your search."
                                : "No platform components have been reported for this cluster."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {!canPlan && (
              <p>
                Your account can view utilities. Upgrade planning permission is
                required to create a change.
              </p>
            )}
          </section>
          <section className="utility-table-surface">
            <header>
              <CalendarDays size={16} />
              <h2>Upcoming changes</h2>
              <span>Recorded maintenance starts · your local timezone</span>
            </header>
            {pending ? (
              <p>Loading utility plans…</p>
            ) : state.error ? (
              <p>Maintenance records are unavailable.</p>
            ) : (
              scheduled
                .filter((plan) => Date.parse(plan.scheduledFor!) >= now)
                .slice(0, 3)
                .map((plan) => (
                  <div className="utility-change-row" key={plan.planId}>
                    <strong>
                      {plan.utilityEvidence?.label ?? plan.utilityCode}
                    </strong>
                    <span>{plan.status}</span>
                    <span>{formatTime(plan.scheduledFor)}</span>
                    <Button
                      variant="secondary"
                      onClick={() => onReview(plan.planId)}
                    >
                      Review plan
                    </Button>
                  </div>
                ))
            )}
            {!pending &&
              !state.error &&
              !scheduled.some(
                (plan) => Date.parse(plan.scheduledFor!) >= now,
              ) && <p>No upcoming utility maintenance has been recorded.</p>}
          </section>
        </>
      )}
      {view === "Catalogue" && (
        <div className="utility-catalogue-layout">
          <section className="utility-table-surface">
            <header>
              <h2>Utility catalogue</h2>
            </header>
            <p>Current platform adapters and their supported workflows.</p>
            <label className="utility-search">
              <Search size={15} />
              <input
                aria-label="Search utility catalogue"
                placeholder="Search utilities"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <label className="utility-category">
              Category{" "}
              <select
                aria-label="Utility category"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                {[
                  "All",
                  ...new Set(utilityCatalogue.map((item) => item.category)),
                ].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            {catalog.map((item) => (
              <button
                type="button"
                className={`utility-catalogue-item ${entry.code === item.code ? "selected" : ""}`}
                key={item.code}
                onClick={() => setCatalogueCode(item.code)}
                aria-pressed={entry.code === item.code}
              >
                <Wrench size={20} />
                <span>
                  <strong>{item.name}</strong>
                  <small>{item.description}</small>
                </span>
                <span>
                  {item.planning
                    ? "Upgrade planning"
                    : "Upgrade not available yet"}
                </span>
              </button>
            ))}
            {!catalog.length && (
              <p>No catalogue entries match these filters.</p>
            )}
          </section>
          <aside
            className="utility-catalogue-detail"
            aria-label="Utility details"
          >
            <ShieldCheck size={25} />
            <h2>{entry.name}</h2>
            <p>{entry.description}</p>
            <dl>
              <dt>Category</dt>
              <dd>{entry.category}</dd>
              <dt>Package</dt>
              <dd>{entry.chart}</dd>
              <dt>Target cluster</dt>
              <dd>{selected?.clusterName ?? "Select a cluster"}</dd>
              <dt>Reported chart</dt>
              <dd>{selectedUtility?.version ?? "Not reported"}</dd>
            </dl>
            {entry.source && (
              <a href={entry.source} target="_blank" rel="noreferrer">
                Official chart releases
              </a>
            )}
            <h3>Available workflow</h3>
            <p>
              {entry.planning
                ? "Create an upgrade draft for an installed utility, then submit it for review. Compatibility and execution remain gated."
                : "Upgrades for this component are not available from System Utilities yet."}
            </p>
            {upgradeAction(
              entry.code,
              Boolean(selectedUtility?.reported),
              entry.planning,
            )}
            <p className="utility-install-note">
              New utility registration and installation are not enabled in this
              release. Catalogue entries describe existing adapters; they are
              not approved installation templates.
            </p>
          </aside>
        </div>
      )}
      {(view === "Change plans" || view === "Maintenance & history") && (
        <section className="utility-table-surface">
          <header>
            <h2>{view}</h2>
            <span>Utility plans for the selected cluster</span>
          </header>
          {pending ? (
            <p>Loading utility plans…</p>
          ) : state.error ? (
            <p role="alert">
              Utility plans could not be loaded. Refresh to retry.
            </p>
          ) : (
            <div className="utility-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Utility</th>
                    <th>Version change</th>
                    <th>Status</th>
                    <th>Maintenance start</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visiblePlans.map((plan) => (
                    <tr key={plan.planId}>
                      <td>
                        <strong>
                          {plan.utilityEvidence?.label ?? plan.utilityCode}
                        </strong>
                      </td>
                      <td>
                        {plan.currentVersion} → {plan.targetVersion}
                      </td>
                      <td>{plan.status}</td>
                      <td>{formatTime(plan.scheduledFor)}</td>
                      <td>
                        <Button
                          variant="secondary"
                          onClick={() => onReview(plan.planId)}
                        >
                          Review plan
                        </Button>
                      </td>
                    </tr>
                  ))}
                  {!visiblePlans.length && (
                    <tr>
                      <td colSpan={5}>
                        No utility changes have been recorded for this cluster.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          <p>
            Approval records the request. It does not deploy the utility; GitOps
            execution is not enabled yet.
          </p>
        </section>
      )}
    </section>
  );
}
