"use client";

import { useMemo, useState } from "react";
import { Activity, Boxes, ChevronRight, Database, Layers3, Network, Search, Server, ShieldAlert } from "lucide-react";
import type { Assessment, SourceInventory } from "./model";
import styles from "./topology-workspace.module.css";

type Resource = SourceInventory["resources"][number];
const workloads = new Set(["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod", "ReplicaSet"]);
const dataKinds = new Set(["PersistentVolumeClaim", "PersistentVolume", "StorageClass"]);
const networkKinds = new Set(["Service", "Ingress", "NetworkPolicy", "EndpointSlice"]);
const configKinds = new Set(["ConfigMap", "Secret", "ServiceAccount"]);
function category(kind: string) {
  if (workloads.has(kind)) return "workload";
  if (dataKinds.has(kind)) return "data";
  if (networkKinds.has(kind)) return "network";
  if (configKinds.has(kind)) return "config";
  return "other";
}
function identity(item: Resource) {
  return [item.apiVersion, item.kind, item.namespace ?? "", item.name ?? ""].join("|");
}
export function MigrationTopologyWorkspace({
  inventory, assessment, chosenNamespaces, onChooseNamespace,
}: {
  inventory: SourceInventory;
  assessment: Assessment;
  chosenNamespaces: string[];
  onChooseNamespace: (namespace: string) => void;
}) {
  const [view, setView] = useState<"overview" | "namespace" | "workload">("overview");
  const [selectedResource, setSelectedResource] = useState("");
  const [search, setSearch] = useState("");
  const source = inventory.resources.filter(r => r.name && r.namespace);
  const namespaces = useMemo(() => [...new Set(source.map(r => r.namespace as string))].sort(), [inventory]);
  const selectedNamespace = chosenNamespaces[0] && namespaces.includes(chosenNamespaces[0]) ? chosenNamespaces[0] : namespaces[0] ?? "";
  const visible = source.filter(r => r.namespace === selectedNamespace);
  const groups = {workload: visible.filter(r => category(r.kind) === "workload"), network: visible.filter(r => category(r.kind) === "network"), config: visible.filter(r => category(r.kind) === "config"), data: visible.filter(r => category(r.kind) === "data")};
  const candidates = visible.filter(r => workloads.has(r.kind));
  const focus = visible.find(r => identity(r) === selectedResource) ?? candidates[0] ?? visible[0];
  const relatedFindings = assessment.findings.filter(f =>
    (!f.namespace || f.namespace === selectedNamespace) &&
    (!f.resourceName || !focus || f.resourceName === focus.name));
  const explicitDependencies = [...new Set(relatedFindings.flatMap(f => f.dependencies ?? []))];
  const blockers = assessment.findings.filter(f => f.severity === "BLOCKER").length;
  const included = source.filter(r => chosenNamespaces.includes(r.namespace ?? ""));
  const named = (items: Resource[], limit = 4) => items.filter(r=>r.name).slice(0,limit);
  return (
    <section className={styles.wrap} aria-label="Migration dependency visualization">
      <div className={styles.header}>
        <div><span className={styles.kicker}>NAVIGAN / MIGRATION INTELLIGENCE</span><h2>Migration topology & dependency explorer</h2><p>Source inventory evidence · Select a namespace to inspect its workloads and verified assessment dependencies</p></div>
        <div className={styles.viewToggle} role="group" aria-label="Topology view">
          <button className={view==="overview"?styles.active:""} onClick={()=>setView("overview")}>Overview</button>
          <button className={view==="namespace"?styles.active:""} onClick={()=>setView("namespace")}>Namespaces</button>
          <button className={view==="workload"?styles.active:""} onClick={()=>setView("workload")}>Workloads</button>
        </div>
      </div>
      <div className={styles.metrics}>
        <div><span>DISCOVERED NAMESPACES</span><strong>{namespaces.length}</strong><small>From current source inventory</small></div>
        <div><span>IN-SCOPE RESOURCES</span><strong>{included.length}</strong><small>{chosenNamespaces.length} selected namespaces</small></div>
        <div><span>WORKLOADS IN SCOPE</span><strong>{included.filter(r=>workloads.has(r.kind)).length}</strong><small>Discovered workload objects</small></div>
        <div><span>ASSESSMENT BLOCKERS</span><strong>{blockers}</strong><small>Source assessment findings</small></div>
      </div>
      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <div className={styles.sidebarHeading}><strong>Namespace explorer</strong><span>{namespaces.length}</span></div>
          <label className={styles.search}><Search size={14}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Find namespace"/></label>
          <div className={styles.namespaceList}>
            {namespaces.filter(n=>n.toLowerCase().includes(search.toLowerCase())).map(n=>{
              const entries=source.filter(r=>r.namespace===n);
              return <button key={n} className={n===selectedNamespace?styles.selectedNamespace:""} onClick={()=>{onChooseNamespace(n);setSelectedResource("");setView("namespace");}}>
                <Boxes size={16}/><span><b>{n}</b><small>{entries.filter(r=>workloads.has(r.kind)).length} workloads · {entries.length} resources</small></span><ChevronRight size={14}/>
              </button>;
            })}
          </div>
          <div className={styles.legend}><strong>Dependency evidence</strong><p>Solid relationships require an explicit link in assessment evidence. Inventory proximity alone does not establish a dependency.</p><span><i className={styles.dotGreen}/> Discovered resources</span><span><i className={styles.dotOrange}/> Review needed</span></div>
        </aside>
        <div className={styles.canvas}>
          <div className={styles.canvasHeading}><div><span className={styles.kicker}>{view==="overview"?"DISCOVERY OVERVIEW":view==="namespace"?"NAMESPACE TOPOLOGY":"WORKLOAD DETAIL"}</span><h3>{view==="overview"?"Source estate":view==="namespace"?selectedNamespace:focus?.name??"No workload discovered"}</h3></div><span className={styles.evidence}>Read-only · Inventory {inventory.inventoryVersion}</span></div>
          {view==="overview" ? (
            <div className={styles.overview}>
              <div className={styles.sourceNode}><Server size={22}/><b>Source Kubernetes</b><small>Kubernetes {inventory.sourceKubernetesVersion}</small></div>
              <div className={styles.guideLine}/>
              <div className={styles.namespaceCards}>
                {namespaces.slice(0,12).map(n=><button key={n} onClick={()=>{onChooseNamespace(n);setView("namespace");}}><Boxes size={19}/><b>{n}</b><span>{source.filter(r=>r.namespace===n).length} inventoried resources</span><ChevronRight size={15}/></button>)}
              </div>
              {namespaces.length>12&&<small>Showing 12 of {namespaces.length} namespaces. Use the explorer to view others.</small>}
            </div>
          ) : view==="namespace" ? (
            <div className={styles.topology}>
              <div className={styles.root}><Layers3 size={19}/><b>{selectedNamespace}</b><small>{visible.length} inventoried resources</small></div>
              <div className={styles.fanLine}/>
              <div className={styles.groupGrid}>
                {(["workload","network","config","data"] as const).map(key=><div key={key} className={styles.group}>
                  <div className={styles.groupTitle}>{key==="data"?<Database size={17}/>:key==="network"?<Network size={17}/>:key==="workload"?<Boxes size={17}/>:<Layers3 size={17}/>}<b>{key==="config"?"Configuration & identity":key==="data"?"Data & storage":key==="network"?"Networking":"Workloads"}</b><span>{groups[key].length}</span></div>
                  <div className={styles.groupItems}>{named(groups[key],5).map(r=><button key={identity(r)} onClick={()=>{setSelectedResource(identity(r));setView("workload");}}><span>{r.kind}</span><b title={r.name??""}>{r.name}</b></button>)}{groups[key].length===0&&<small>No objects in inventory</small>}{groups[key].length>5&&<small>+{groups[key].length-5} more in inventory</small>}</div>
                </div>)}
              </div>
              <p className={styles.caution}><ShieldAlert size={15}/> Resource groups are inventory classifications, not asserted runtime dependency edges.</p>
            </div>
          ) : (
            <div className={styles.detail}>
              <div className={styles.workloadPicker}>{candidates.slice(0,30).map(r=><button key={identity(r)} className={focus&&identity(r)===identity(focus)?styles.activeWorkload:""} onClick={()=>setSelectedResource(identity(r))}>{r.name}</button>)}</div>
              {focus ? <><div className={styles.focus}><Activity size={24}/><span><small>{focus.kind} · {focus.namespace}</small><b>{focus.name}</b></span></div><div className={styles.dependencyGrid}>
                {(["network","config","data"] as const).map(key=><section key={key}><h4>{key==="network"?"Networking":key==="config"?"Config & identity":"Data & storage"}</h4>{named(groups[key],8).map(r=><div key={identity(r)}><b>{r.name}</b><small>{r.kind} · relationship unverified</small></div>)}{groups[key].length===0&&<p>No related objects inventoried in this namespace</p>}</section>)}
              </div><div className={styles.confirmed}><strong>Assessment dependency references ({explicitDependencies.length})</strong>{explicitDependencies.length?explicitDependencies.map(d=><span key={d}>{d}</span>):<p>No explicit relationship references for this workload in the current assessment. Do not infer edges from co-location.</p>}</div></> : <p>No resources available for this namespace.</p>}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
