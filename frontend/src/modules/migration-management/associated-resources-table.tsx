"use client";
import { useState } from "react";
import styles from "./migration-experience.module.css";

type Resource = {
  apiVersion?: string;
  kind: string;
  namespace?: string | null;
  name: string;
};
export function AssociatedResourcesTable({
  resources,
}: {
  resources: Resource[];
}) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(0);
  const matches = resources.filter(
    (r) =>
      (!kind || r.kind === kind) &&
      `${r.name} ${r.namespace ?? "Cluster"} ${r.kind}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const pages = Math.max(1, Math.ceil(matches.length / 10));
  const current = Math.min(page, pages - 1);
  return (
    <div className={styles.surface}>
      <div className={styles.resourceTools}>
        <label>
          Find associated resource
          <input
            type="search"
            value={search}
            placeholder="Name, namespace or kind"
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <label>
          Resource kind
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All kinds</option>
            {[...new Set(resources.map((r) => r.kind))].sort().map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
      </div>
      <table className={styles.resourceTable} aria-label="Associated resources">
        <thead>
          <tr>
            <th scope="col">Resource</th>
            <th scope="col">Kind</th>
            <th scope="col">Namespace</th>
          </tr>
        </thead>
        <tbody>
          {matches.slice(current * 10, current * 10 + 10).map((r) => (
            <tr key={`${r.apiVersion}/${r.kind}/${r.namespace}/${r.name}`}>
              <td>{r.name}</td>
              <td>{r.kind}</td>
              <td>{r.namespace || "Cluster scoped"}</td>
            </tr>
          ))}
          {!matches.length && (
            <tr>
              <td colSpan={3}>No associated resources match these filters.</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className={styles.tableFooter}>
        <span>
          {matches.length ? current * 10 + 1 : 0}–
          {Math.min((current + 1) * 10, matches.length)} of {matches.length}{" "}
          resources
        </span>
        {pages > 1 && (
          <div>
            <button
              type="button"
              disabled={!current}
              onClick={() => setPage(current - 1)}
            >
              Previous resources
            </button>
            <span>
              Page {current + 1} of {pages}
            </span>
            <button
              type="button"
              disabled={current + 1 >= pages}
              onClick={() => setPage(current + 1)}
            >
              Next resources
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
