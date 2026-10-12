"use client";
import {useMemo,useState} from "react";
import {Boxes, GitBranch, Search, ZoomIn, ZoomOut, RotateCcw} from "lucide-react";
import styles from "./scope-topology.module.css";

export type TopologyResource={kind:string;namespace:string|null;name:string;selected:boolean;references:{kind:string;name:string;present:boolean}[];potentialClaims:{name:string}[]};
type Props={namespaces:string[];resources:TopologyResource[];coverageKnown:boolean;onSelect?:(resource:TopologyResource)=>void;readOnly?:boolean};
export function ScopeTopology({namespaces,resources,coverageKnown,onSelect,readOnly}:Props){
 const [focus,setFocus]=useState<string|null>(null);
 const [filter,setFilter]=useState("");
 const [showUnselected,setShowUnselected]=useState(true);
 const [zoom,setZoom]=useState(100);
 const visible=useMemo(()=>resources.filter(r=>(showUnselected||r.selected)&&(!filter||`${r.namespace} ${r.kind} ${r.name}`.toLowerCase().includes(filter.toLowerCase()))),[resources,filter,showUnselected]);
 const focused=resources.find(r=>`${r.namespace}/${r.kind}/${r.name}`===focus);
 return <section className={styles.shell} aria-label="Application workload dependency map">
  <div className={styles.header}>
   <div><h3>Application topology</h3><p>Source workloads and their discovered dependencies in the selected namespaces.</p></div>
   <div className={styles.legend}><span><i className={styles.selected}/> In draft</span><span><i className={styles.observed}/> Observed</span><span><i className={styles.unverified}/> Needs verification</span></div>
  </div>
  <div className={styles.toolbar}>
   <label className={styles.search}><Search size={14}/><input aria-label="Search topology" placeholder="Find workload…" value={filter} onChange={e=>setFilter(e.target.value)}/></label>
   <label className={styles.toggle}><input type="checkbox" checked={showUnselected} onChange={e=>setShowUnselected(e.target.checked)}/> Show discovered resources</label>
   <div className={styles.zoom}><button aria-label="Zoom out" onClick={()=>setZoom(v=>Math.max(70,v-10))}><ZoomOut size={15}/></button><span>{zoom}%</span><button aria-label="Zoom in" onClick={()=>setZoom(v=>Math.min(130,v+10))}><ZoomIn size={15}/></button><button aria-label="Reset zoom" onClick={()=>setZoom(100)}><RotateCcw size={15}/></button></div>
  </div>
  {!coverageKnown&&<p className={styles.warning}><strong>Relationship evidence unavailable.</strong> This older assessment does not include reliable dependency references. Nodes are real inventory; no connections are assumed. Reassess the source to populate verified links.</p>}
  <div className={styles.canvasViewport}><div className={styles.canvas} style={{zoom:`${zoom}%`}}>
   {namespaces.map((ns,index)=>{
     const nodes=visible.filter(r=>r.namespace===ns);
     return <div key={ns} className={styles.namespace} data-tone={index%2?"green":"blue"}>
      <div className={styles.namespaceHeading}><span><Boxes size={17}/> <strong>{ns}</strong></span><small>{nodes.length} displayed · {nodes.filter(r=>r.selected).length} in draft</small></div>
      {nodes.length ? <div className={styles.groups}>{nodes.map(resource=>{
       const id=`${ns}/${resource.kind}/${resource.name}`;
       return <div className={styles.group} key={id}>
        <button className={resource.selected?styles.nodeSelected:styles.node} onClick={()=>setFocus(id)} aria-label={`Inspect ${resource.kind} ${resource.name}`}>
         <Boxes size={19}/><span><strong>{resource.name}</strong><small>{resource.kind}</small></span>{resource.selected&&<span className={styles.check}>✓</span>}
        </button>
        {!!resource.references.length&&<><div className={styles.connector} aria-label="Observed dependency links"/><div className={styles.deps}>{resource.references.map((ref,j)=><button key={j} onClick={()=>setFocus(id)} className={ref.present?styles.dep:styles.missing}><GitBranch size={14}/><span><strong>{ref.name}</strong><small>{ref.kind} · {ref.present?"Observed":"Missing target in inventory"}</small></span></button>)}</div></>}
        {!!resource.potentialClaims.length&&<div className={styles.claims}><small>Potential storage · unverified</small>{resource.potentialClaims.map(p=><span key={p.name}>{p.name}</span>)}</div>}
       </div>;
      })}</div>:<p className={styles.empty}>No workloads match this namespace and filter.</p>}
     </div>;
   })}
   {!namespaces.length&&<p className={styles.empty}>Select namespaces and run Analyze selected scope to see the topology.</p>}
  </div></div>
  <div className={styles.footer}><span>Solid connectors = directly recorded source references. Unverified storage candidates are never displayed as confirmed links.</span></div>
  {focused&&<div className={styles.inspector} role="region" aria-label="Selected topology resource">
   <div><strong>{focused.name}</strong><button onClick={()=>setFocus(null)} aria-label="Close inspection">×</button></div>
   <p>{focused.namespace} / {focused.kind}</p>
   <p>{focused.selected?"Already included in migration draft":"Discovered candidate; not included in draft"}</p>
   <p>{focused.references.length} recorded reference(s). {coverageKnown?"Evidence available":"Reference coverage not established."}</p>
   {!focused.selected&&onSelect&&<button className={styles.add} disabled={readOnly} onClick={()=>{onSelect(focused);setFocus(null)}}>Add workload to draft</button>}
  </div>}
 </section>;
}
