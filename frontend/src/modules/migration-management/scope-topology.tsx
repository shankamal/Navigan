"use client";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  ChevronRight,
  Database,
  Layers3,
  Network,
  RotateCcw,
  Search,
  ZoomIn,
  ZoomOut,
  X,
} from "lucide-react";
import styles from "./scope-topology.module.css";

export type TopologyResource = {
  kind: string;
  namespace: string | null;
  name: string;
  selected: boolean;
  references: { kind: string; name: string; present: boolean }[];
  potentialClaims: { name: string }[];
};
type SupportingResource = {
  kind: string;
  namespace: string | null;
  name: string;
  selected: boolean;
};
type Props = {
  namespaces: string[];
  resources: TopologyResource[];
  supportingResources?: SupportingResource[];
  coverageKnown: boolean;
  onSelect?: (resource: TopologyResource) => void;
  readOnly?: boolean;
};
type Node = {
  id: string;
  name: string;
  kind: string;
  namespace: string | null;
  selected: boolean;
  type: "workload" | "support";
  present: boolean;
  x: number;
  y: number;
};
type Edge = { from: string; to: string; present: boolean };
const key = (r: { namespace: string | null; kind: string; name: string }) =>
  JSON.stringify([r.namespace, r.kind, r.name]);
const iconFor = (kind: string) =>
  kind === "PersistentVolumeClaim" || kind === "StatefulSet" ? (
    <Database size={17} />
  ) : kind === "Service" || kind === "Ingress" ? (
    <Network size={17} />
  ) : (
    <Layers3 size={17} />
  );

export function ScopeTopology({
  namespaces,
  resources,
  supportingResources = [],
  coverageKnown,
  onSelect,
  readOnly,
}: Props) {
  const [namespace, setNamespace] = useState("ALL");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(100);
  const [showAllSupport, setShowAllSupport] = useState(false);
  const [onlyDraft, setOnlyDraft] = useState(false);
  useEffect(() => {
    if (namespace !== "ALL" && !namespaces.includes(namespace)) {
      setNamespace("ALL");
      setSelectedId(null);
    }
  }, [namespaces, namespace]);
  const scopedWorkloads = useMemo(
    () =>
      resources.filter(
        (r) =>
          namespaces.includes(r.namespace ?? "") &&
          (namespace === "ALL" || r.namespace === namespace),
      ),
    [resources, namespaces, namespace],
  );
  const scopedSupporting = useMemo(
    () =>
      supportingResources.filter(
        (r) =>
          namespaces.includes(r.namespace ?? "") &&
          (namespace === "ALL" || r.namespace === namespace),
      ),
    [supportingResources, namespaces, namespace],
  );
  const matches = (r: {
    name: string;
    kind: string;
    namespace: string | null;
  }) =>
    [r.name, r.kind, r.namespace]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase());
  const workloads = scopedWorkloads.filter(
    (r) => (!onlyDraft || r.selected) && matches(r),
  );
  const referenceKeys = new Set(
    workloads.flatMap((r) =>
      coverageKnown
        ? r.references.map((ref) =>
            key({ namespace: r.namespace, kind: ref.kind, name: ref.name }),
          )
        : [],
    ),
  );
  const showSupport = scopedSupporting.filter(
    (r) =>
      (showAllSupport || referenceKeys.has(key(r)) || r.selected) &&
      (matches(r) || referenceKeys.has(key(r))),
  );
  const missingRefs = coverageKnown
    ? workloads.flatMap((r) =>
        r.references
          .filter(
            (ref) =>
              !scopedSupporting.some(
                (p) =>
                  p.kind === ref.kind &&
                  p.name === ref.name &&
                  p.namespace === r.namespace,
              ),
          )
          .map((ref) => ({
            kind: ref.kind,
            name: ref.name,
            namespace: r.namespace,
            selected: false,
            present: false,
          })),
      )
    : [];
  const supporting = [
    ...showSupport.map((r) => ({ ...r, present: true })),
    ...missingRefs.filter(
      (r, i, a) => a.findIndex((x) => key(x) === key(r)) === i,
    ),
  ];
  const rowHeight = 78,
    top = 62,
    nodeWidth = 240,
    supportX = 515,
    graphWidth = 790;
  const graphHeight = Math.max(
    330,
    top + Math.max(workloads.length, supporting.length) * rowHeight + 22,
  );
  const nodes: Node[] = [
    ...workloads.map((r, i) => ({
      ...r,
      id: key(r),
      type: "workload" as const,
      present: true,
      x: 35,
      y: top + i * rowHeight,
    })),
    ...supporting.map((r, i) => ({
      ...r,
      id: key(r),
      type: "support" as const,
      x: supportX,
      y: top + i * rowHeight,
    })),
  ];
  const index = new Map(nodes.map((n) => [n.id, n]));
  const edges: Edge[] = coverageKnown
    ? workloads.flatMap((r) =>
        r.references
          .map((ref) => ({
            from: key(r),
            to: key({ namespace: r.namespace, kind: ref.kind, name: ref.name }),
            present: ref.present,
          }))
          .filter((e) => index.has(e.to)),
      )
    : [];
  const focus = nodes.find((n) => n.id === selectedId);
  const chosenWorkload = resources.find((r) => key(r) === selectedId);
  const focusedReferences = chosenWorkload?.references ?? [];
  const selectedWorkloads = scopedWorkloads.filter((r) => r.selected).length;
  const selectedSupport = scopedSupporting.filter((r) => r.selected).length;
  const displayNamespaces = namespace === "ALL" ? namespaces : [namespace];
  return (
    <section
      className={styles.hmShell}
      aria-label="Headlamp-inspired application resource map"
    >
      <div className={styles.hmHeader}>
        <div>
          <span className={styles.hmEyebrow}>
            SCOPE &amp; TARGET / APPLICATION MAP
          </span>
          <h3>Application resource map</h3>
          <p>Select a namespace, inspect resources and plan migration scope</p>
        </div>
        <div className={styles.hmLegend}>
          <span>
            <i className={styles.hmGreen} /> In migration draft
          </span>
          <span>
            <i className={styles.hmWhite} /> Discovered
          </span>
          <span>
            <i className={styles.hmAmber} /> Missing reference
          </span>
        </div>
      </div>
      <div className={styles.hmTools}>
        <label className={styles.hmSearch}>
          <Search size={15} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find resources..."
            aria-label="Find resources in map"
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={onlyDraft}
            onChange={(e) => setOnlyDraft(e.target.checked)}
          />{" "}
          In draft only
        </label>
        <label>
          <input
            type="checkbox"
            checked={showAllSupport}
            onChange={(e) => setShowAllSupport(e.target.checked)}
          />{" "}
          All supporting resources
        </label>
        <div className={styles.hmZoom}>
          <button
            aria-label="Zoom out"
            onClick={() => setZoom((v) => Math.max(60, v - 10))}
          >
            <ZoomOut size={15} />
          </button>
          <span>{zoom}%</span>
          <button
            aria-label="Zoom in"
            onClick={() => setZoom((v) => Math.min(140, v + 10))}
          >
            <ZoomIn size={15} />
          </button>
          <button aria-label="Reset zoom" onClick={() => setZoom(100)}>
            <RotateCcw size={15} />
          </button>
        </div>
      </div>
      <div className={styles.hmWorkspace}>
        <aside className={styles.hmNamespaces} aria-label="Namespace filter">
          <div className={styles.hmSidebarTitle}>
            NAMESPACES <span>{namespaces.length}</span>
          </div>
          <button
            className={
              namespace === "ALL"
                ? styles.hmNamespaceActive
                : styles.hmNamespace
            }
            onClick={() => {
              setNamespace("ALL");
              setSelectedId(null);
            }}
          >
            <Boxes size={16} />
            <span>
              All namespaces
              <small>
                {
                  resources.filter((r) =>
                    namespaces.includes(r.namespace ?? ""),
                  ).length
                }{" "}
                workloads
              </small>
            </span>
            <ChevronRight size={14} />
          </button>
          {namespaces.map((ns) => (
            <button
              key={ns}
              className={
                namespace === ns ? styles.hmNamespaceActive : styles.hmNamespace
              }
              onClick={() => {
                setNamespace(ns);
                setSelectedId(null);
              }}
            >
              <Boxes size={16} />
              <span>
                {ns}
                <small>
                  {resources.filter((r) => r.namespace === ns).length} workloads
                </small>
              </span>
              <ChevronRight size={14} />
            </button>
          ))}
          <div className={styles.hmSidebarFooter}>
            <strong>Source evidence</strong>
            <span>
              {coverageKnown
                ? "Reference inventory available"
                : "References not collected"}
            </span>
            <small>
              Only source-observed references create connecting lines.
            </small>
          </div>
        </aside>
        <div className={styles.hmMain}>
          <div className={styles.hmStats}>
            <span>
              <b>{scopedWorkloads.length}</b> workloads
            </span>
            <span>
              <b>{selectedWorkloads}</b> included workloads
            </span>
            <span>
              <b>{selectedSupport}</b> included supporting resources
            </span>
            <span>
              <b>{edges.length}</b> visible references
            </span>
          </div>
          {!coverageKnown && (
            <div className={styles.hmNotice}>
              <AlertTriangle size={16} />
              <span>
                <strong>Relationship evidence not collected.</strong> The map
                shows discovered resources without assuming connections.
                Reassess the source to populate verified links.
              </span>
            </div>
          )}
          <div className={styles.hmCanvasScroll}>
            <div
              className={styles.hmScaled}
              style={{
                width: (graphWidth * zoom) / 100,
                height: (graphHeight * zoom) / 100,
              }}
            >
              <div
                className={styles.hmCanvas}
                style={{
                  width: graphWidth,
                  height: graphHeight,
                  transform: `scale(${zoom / 100})`,
                }}
              >
                <div className={styles.hmGroupLabel} style={{ left: 35 }}>
                  WORKLOADS <small>{workloads.length}</small>
                </div>
                <div className={styles.hmGroupLabel} style={{ left: supportX }}>
                  SUPPORTING RESOURCES <small>{supporting.length}</small>
                </div>
                <svg
                  className={styles.hmSvg}
                  viewBox={`0 0 ${graphWidth} ${graphHeight}`}
                  aria-hidden="true"
                >
                  {edges.map((e, i) => {
                    const a = index.get(e.from)!,
                      b = index.get(e.to)!;
                    const sx = a.x + nodeWidth,
                      sy = a.y + 28,
                      ex = b.x,
                      ey = b.y + 28,
                      mid = (sx + ex) / 2;
                    return (
                      <path
                        key={i}
                        d={`M ${sx} ${sy} C ${mid} ${sy}, ${mid} ${ey}, ${ex} ${ey}`}
                        fill="none"
                        stroke={e.present ? "#78ac35" : "#d59b40"}
                        strokeWidth={2}
                        strokeDasharray={e.present ? undefined : "6 5"}
                      />
                    );
                  })}
                </svg>
                {nodes.map((n) => (
                  <button
                    type="button"
                    key={n.id}
                    style={{ left: n.x, top: n.y, width: nodeWidth }}
                    className={[
                      styles.hmNode,
                      n.selected ? styles.hmNodeSelected : "",
                      !n.present ? styles.hmNodeMissing : "",
                      selectedId === n.id ? styles.hmNodeFocused : "",
                    ].join(" ")}
                    onClick={() => setSelectedId(n.id)}
                  >
                    <span className={styles.hmNodeIcon}>{iconFor(n.kind)}</span>
                    <span className={styles.hmNodeText}>
                      <strong>{n.name}</strong>
                      <small>
                        {n.kind} · {n.namespace}
                      </small>
                    </span>
                    {n.selected && (
                      <CheckCircle2 size={16} className={styles.hmCheck} />
                    )}
                  </button>
                ))}
                {!nodes.length && (
                  <div className={styles.hmEmpty}>
                    No matching resources in this namespace. Adjust the filters
                    or search.
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className={styles.hmCanvasFooter}>
            <span>{displayNamespaces.join(", ")}</span>
            <span>
              Green nodes are included in the draft; resource discovery alone
              does not imply a dependency
            </span>
          </div>
        </div>
        <aside
          className={styles.hmInspector}
          aria-label="Resource inspection and migration scope"
        >
          <div className={styles.hmSidebarTitle}>SCOPE INSPECTOR</div>
          {focus ? (
            <>
              <div className={styles.hmInspectHeading}>
                <span>
                  {focus.type === "workload"
                    ? "Workload"
                    : "Supporting resource"}
                </span>
                <button
                  onClick={() => setSelectedId(null)}
                  aria-label="Close resource inspector"
                >
                  <X size={17} />
                </button>
              </div>
              <h4>{focus.name}</h4>
              <p>
                {focus.kind} · {focus.namespace}
              </p>
              <div className={styles.hmInspectState}>
                {focus.selected
                  ? "Included in migration draft"
                  : focus.present
                    ? "Discovered — not selected"
                    : "Referenced but not in inventory"}
              </div>
              {chosenWorkload && (
                <div className={styles.hmReferenceList}>
                  <strong>
                    Recorded references (
                    {coverageKnown ? focusedReferences.length : 0})
                  </strong>
                  {coverageKnown &&
                    focusedReferences.map((ref, i) => (
                      <div key={i}>
                        {ref.kind} · {ref.name}{" "}
                        <small>{ref.present ? "Found" : "Missing"}</small>
                      </div>
                    ))}
                  {!coverageKnown && (
                    <small>
                      Relationship evidence unavailable in this assessment
                    </small>
                  )}
                  {coverageKnown && !focusedReferences.length && (
                    <small>No explicit references recorded</small>
                  )}
                </div>
              )}
              {!focus.selected && chosenWorkload && onSelect && (
                <button
                  className={styles.hmAdd}
                  disabled={readOnly}
                  onClick={() => onSelect(chosenWorkload)}
                >
                  Add workload to draft
                </button>
              )}
            </>
          ) : (
            <>
              <p className={styles.hmInspectorHint}>
                Select a node on the map to inspect its resource details and
                migration selection.
              </p>
              <div className={styles.hmScopeTotals}>
                <div>
                  <strong>{selectedWorkloads}</strong>
                  <span>Selected workloads</span>
                </div>
                <div>
                  <strong>{selectedSupport}</strong>
                  <span>Supporting resources</span>
                </div>
                <div>
                  <strong>{scopedWorkloads.length}</strong>
                  <span>Discovered workloads</span>
                </div>
              </div>
            </>
          )}
          <div className={styles.hmInspectorFoot}>
            Migration planning only. No source resources are modified.
          </div>
        </aside>
      </div>
    </section>
  );
}
