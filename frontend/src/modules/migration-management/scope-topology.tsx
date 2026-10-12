"use client";
import {useMemo,useState} from "react";
import {Boxes, GitBranch, Search, ZoomIn, ZoomOut, RotateCcw, Database, AlertTriangle, CheckCircle2, Layers3} from "lucide-react";
import styles from "./scope-topology.module.css";
export type TopologyResource={kind:string;namespace:string|null;name:string;selected:boolean;references:{kind:string;name:string;present:boolean}[];potentialClaims:{name:string}[]};
type Props={namespaces:string[];resources:TopologyResource[];coverageKnown:boolean;onSelect?:(resource:TopologyResource)=>void;readOnly?:boolean};
const ident=(r:TopologyResource)=>[r.namespace,r.kind,r.name].join("/");
export function ScopeTopology({namespaces,resources,coverageKnown,onSelect,readOnly}:Props){
 const [focus,setFocus]=useState<string|null>(null);
 const [filter,setFilter]=useState("");
 const [zoom,setZoom]=useState(100);
 const [showUnselected,setShowUnselected]=useState(true);
 const [expanded,setExpanded]=useState<string[]>([]);
 const visible=useMemo(()=>resources.filter(r=>(showUnselected||r.selected)&&(!filter||[r.namespace,r.kind,r.name,...r.references.map(x=>x.name)].join(" ").toLowerCase().includes(filter.toLowerCase()))),[resources,filter,showUnselected]);
 const focused=resources.find(r=>ident(r)===focus);
 const displayed=namespaces.filter(ns=>visible.some(r=>r.namespace===ns));
 const referenceCount=visible.reduce((a,r)=>a+r.references.length,0);
 return <section className={styles.shell} aria-label="Application workload dependency map">
  <header className={styles.header}>
   <div><h3>Discovered application topology</h3><p>Workloads and their actual recorded resource references, organized by namespace</p></div>
   <div className={styles.legend}><span><i className={styles.selected}/> In migration draft</span><span><i className={styles.observed}/> Recorded reference</span><span><i className={styles.unverified}/> Needs review</span></div>
  </header>
  <div className={styles.toolbar}>
    <label className={styles.search}><Search size={15}/><input aria-label="Search topology" placeholder="Search workloads or references" value={filter} onChange={e=>setFilter(e.target.value)}/></label>
    <label className={styles.toggle}><input type="checkbox" checked={showUnselected} onChange={e=>setShowUnselected(e.target.checked)}/> Show discovered</label>
    <div className={styles.zoom}><button aria-label="Zoom out" onClick={()=>setZoom(v=>Math.max(80,v-10))}><ZoomOut size={15}/></button><span>{zoom}%</span><button aria-label="Zoom in" onClick={()=>setZoom(v=>Math.min(120,v+10))}><ZoomIn size={15}/></button><button aria-label="Reset zoom" onClick={()=>setZoom(100)}><RotateCcw size={15}/></button></div>
  </div>
  <div className={styles.stats}><span><b>{displayed.length}</b> namespaces</span><span><b>{visible.length}</b> workloads</span><span><b>{referenceCount}</b> recorded references</span><span><b>{visible.reduce((a,r)=>a+r.potentialClaims.length,0)}</b> unverified storage candidates</span></div>
  {!coverageKnown&&<div className={styles.warning}><AlertTriangle size={17}/><span><strong>Relationship evidence unavailable for this assessment.</strong> Workloads below are verified inventory objects. No relationship lines are fabricated. Reassess the source to collect dependency references.</span></div>}
  <div className={styles.canvasViewport}><div className={styles.canvas} style={{zoom:`${zoom}%`}}>
   {displayed.map((ns,index)=>{
    const nodes=visible.filter(r=>r.namespace===ns);
    const isExpanded=expanded.includes(ns);
    const primary=isExpanded?nodes:nodes.slice(0,5);
    return <section key={ns} className={styles.namespace} data-tone={index%2?"green":"blue"}>
      <div className={styles.namespaceHeading}><span><Boxes size={17}/><strong>{ns}</strong><small>{nodes.length} workload{nodes.length===1?"":"s"}</small></span><span className={styles.namespaceMeta}>{nodes.filter(x=>x.selected).length} included{nodes.length>5&&<button onClick={()=>setExpanded(a=>isExpanded?a.filter(x=>x!==ns):[...a,ns])}>{isExpanded?"Show fewer":`Show all ${nodes.length}`}</button>}</span></div>
      <div className={styles.lanes}>{primary.map(resource=>{
        const id=ident(resource);
        return <div className={styles.lane} key={id}>
          <button className={resource.selected?styles.nodeSelected:styles.node} onClick={()=>setFocus(id)} aria-label={`Inspect ${resource.kind} ${resource.name}`}>
            <Layers3 size={17}/><span><strong>{resource.name}</strong><small>{resource.kind}</small></span>{resource.selected&&<CheckCircle2 className={styles.included} size={16}/>}
          </button>
          <div className={styles.relationship}>
            {resource.references.length>0?<><span className={styles.connector}><GitBranch size={13}/> Recorded links</span><div className={styles.deps}>{resource.references.map((ref,j)=><button key={j} onClick={()=>setFocus(id)} className={ref.present?styles.dep:styles.missing}><span><strong>{ref.name}</strong><small>{ref.kind} · {ref.present?"In source inventory":"Not found in inventory"}</small></span></button>)}</div></>:<span className={styles.noLink}>{coverageKnown?"No recorded references for this workload":"Dependency relationships not collected"}</span>}
            {resource.potentialClaims.length>0&&<div className={styles.claims}><Database size={13}/><span>Possible storage:</span>{resource.potentialClaims.map(p=><span key={p.name} className={styles.claim}>{p.name} · unverified</span>)}</div>}
          </div>
        </div>;
      })}</div>
    </section>;
   })}
   {!displayed.length&&<p className={styles.empty}>No workloads match the current namespace selection or search.</p>}
  </div></div>
  <footer className={styles.footer}>Only recorded dependency references are connected. Potential storage volumes remain explicitly unverified until assessed.</footer>
  {focused&&<aside className={styles.inspector} role="region" aria-label="Selected topology resource"><div><strong>{focused.name}</strong><button onClick={()=>setFocus(null)} aria-label="Close inspection">×</button></div><p>{focused.namespace} / {focused.kind}</p><p>{focused.selected?"Included in migration draft":"Discovered candidate; not yet included"}</p><p>{focused.references.length} recorded references · {focused.potentialClaims.length} potential storage candidates</p>{!focused.selected&&onSelect&&<button className={styles.add} disabled={readOnly} onClick={()=>{onSelect(focused);setFocus(null)}}>Add workload to draft</button>}</aside>}
 </section>;
}
