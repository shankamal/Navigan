"use client";
import { useState } from "react";
import {
  Box,
  Boxes,
  GitBranch,
  Database,
  FileText,
  ChevronRight,
  ShieldCheck,
} from "lucide-react";
import type {
  DeploymentEvidence,
  DeploymentWorkloadEvidence,
} from "./deployment-evidence-service";
import journey from "./discovery-journey.module.css";

type Props = {
  evidence: DeploymentEvidence;
  workloads: DeploymentWorkloadEvidence[];
  namespaces: string[];
  onAccess: () => void;
  onWorkloads: (namespace?: string) => void;
  onCollect: () => void;
};
const available = (w: DeploymentWorkloadEvidence) =>
  w.containers.length > 0 &&
  w.containers.every((c) => c.registryEvidence?.status === "AVAILABLE");
function Coverage({
  value,
  total,
  label,
  tone,
}: {
  value: number;
  total: number;
  label: string;
  tone: "repository" | "image";
}) {
  return (
    <div className={`${journey.coverage} ${journey[tone]}`}>
      <span>
        {value} / {total}
      </span>
      <progress value={value} max={Math.max(total, 1)} aria-label={label} />
    </div>
  );
}
export function DiscoveryReview({
  evidence,
  workloads,
  namespaces,
  onAccess,
  onWorkloads,
  onCollect,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const checked = Boolean(evidence.analyzedAt);
  const current = checked && evidence.analysisCurrent !== false;
  const mapped = workloads.filter((w) => w.candidates.length > 0).length;
  const images = workloads.filter(available).length;
  const access = workloads.filter((w) =>
    w.containers.some((c) =>
      ["ACCESS_REQUIRED", "NOT_CONNECTED"].includes(
        c.registryEvidence?.status ?? "",
      ),
    ),
  ).length;
  const registryCount = evidence.configuration?.registries.length ?? 0;
  const rows = namespaces.map((name) => ({
    name,
    workloads: workloads.filter(
      (w) => (w.workload.namespace || "Cluster-scoped") === name,
    ),
  }));
  return (
    <section className={journey.review} aria-label="Discovery evidence summary">
      {!current && (
        <p className={journey.freshness} role="status">
          {checked
            ? "Source checks need refreshing. Counts show the last reported result."
            : "Deployment source checks have not completed. Zero matches do not mean files or images are missing."}
        </p>
      )}
      <div className={journey.totals}>
        <div>
          <Box />
          <span>
            <strong>{namespaces.length}</strong>
            <small>Namespaces</small>
          </span>
        </div>
        <div>
          <Boxes />
          <span>
            <strong>{workloads.length}</strong>
            <small>Workloads</small>
          </span>
        </div>
        <div>
          <GitBranch />
          <span>
            <strong>
              {checked ? `${mapped} / ${workloads.length}` : "Not checked"}
            </strong>
            <small>Repository candidates</small>
            {checked && (
              <Coverage
                value={mapped}
                total={workloads.length}
                label="Repository candidate coverage"
                tone="repository"
              />
            )}
          </span>
        </div>
        <div>
          <Database />
          <span>
            <strong>
              {checked ? `${images} / ${workloads.length}` : "Not checked"}
            </strong>
            <small>Workloads with available images</small>
            {checked && (
              <Coverage
                value={images}
                total={workloads.length}
                label="Image availability coverage"
                tone="image"
              />
            )}
          </span>
        </div>
      </div>
      <div className={journey.sectionTitle}>
        <h3>Source review & next actions</h3>
        <span>Repository matches do not verify the deployed Git revision.</span>
      </div>
      <div className={journey.checklist}>
        <div>
          <ShieldCheck />
          <span>
            <strong>Source access</strong>
            <small>Repositories & registries</small>
          </span>
          <span>
            {registryCount} registr{registryCount === 1 ? "y" : "ies"}{" "}
            configured
            <small>
              {access
                ? `${access} workload${access === 1 ? "" : "s"} report${access === 1 ? "s" : ""} access gaps`
                : "Review connected source access"}
            </small>
          </span>
          <p>Check access to repositories and referenced images.</p>
          <button type="button" onClick={onAccess}>
            Review access
          </button>
        </div>
        <div>
          <GitBranch />
          <span>
            <strong>Deployment definitions</strong>
            <small>Repository candidates</small>
          </span>
          <span>
            {checked ? `${mapped} candidate matches` : "Source checks pending"}
            <small>Deployed revision unverified</small>
          </span>
          <p>Review definitions associated with each workload.</p>
          <button type="button" onClick={() => onWorkloads()}>
            Inspect workloads
          </button>
        </div>
        <div>
          <FileText />
          <span>
            <strong>Files & images</strong>
            <small>Private S3 workspace</small>
          </span>
          <span>
            Review saved workspaces
            <small>Collection is a separate action</small>
          </span>
          <p>Collect definitions and images; resolve missing artifacts.</p>
          <button type="button" onClick={onCollect}>
            Open collection
          </button>
        </div>
      </div>
      <div className={journey.sectionTitle}>
        <h3>Namespace summary</h3>
        {rows.length > 5 && (
          <button type="button" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Show fewer" : `View all ${rows.length} namespaces`}
          </button>
        )}
      </div>
      <div className={journey.tableScroll}>
        <table className={journey.namespaceTable}>
          <thead>
            <tr>
              <th>Namespace</th>
              <th>Workloads</th>
              <th>Repository candidates</th>
              <th>Images available</th>
              <th>
                <span className={journey.srOnly}>Inspect namespace</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {(expanded ? rows : rows.slice(0, 5)).map((row) => (
              <tr key={row.name}>
                <td>
                  <button type="button" onClick={() => onWorkloads(row.name)}>
                    {row.name}
                  </button>
                </td>
                <td>{row.workloads.length}</td>
                <td>
                  {checked ? (
                    <Coverage
                      value={
                        row.workloads.filter((w) => w.candidates.length > 0)
                          .length
                      }
                      total={row.workloads.length}
                      label={`${row.name} repository candidate coverage`}
                      tone="repository"
                    />
                  ) : (
                    "Not checked"
                  )}
                </td>
                <td>
                  {checked ? (
                    <Coverage
                      value={row.workloads.filter(available).length}
                      total={row.workloads.length}
                      label={`${row.name} image availability coverage`}
                      tone="image"
                    />
                  ) : (
                    "Not checked"
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    aria-label={`Inspect namespace ${row.name}`}
                    onClick={() => onWorkloads(row.name)}
                  >
                    <ChevronRight size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <p>No namespaces reported in this inventory.</p>}
      </div>
    </section>
  );
}
