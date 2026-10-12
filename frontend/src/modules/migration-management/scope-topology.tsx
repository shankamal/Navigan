"use client";
import {useMemo,useState} from "react";
import {AlertTriangle,Boxes,CheckCircle2,Database,Layers3,Network,Search,ZoomIn,ZoomOut,RotateCcw,GitBranch,ChevronRight} from "lucide-react";
import styles from "./scope-topology.module.css";
export type TopologyResource={kind:string;namespace:string|null;name:string;selected:boolean;references:{kind:string;name:string;present:boolean}[];potentialClaims:{name:string}[]};
type Props={namespaces:string[];resources:TopologyResource[];coverageKnown:boolean;onSelect?:(resource:TopologyResource)=>void;readOnly?:boolean};
const id=(r:TopologyResource)=>[r.namespace,r.kind,r.name].join("/");
function glyph(kind:string){return kind==="StatefulSet"?<Database size={16}/>:kind==="Service"?<Network size={16}/>:<Layers3 size={16}/>;}
export function ScopeTopology({namespaces,resources,coverageKnown,onSelect,readOnly}:Props){
 const [focus,setFocus]=useState<string|null>(null);
 const [search,setSearch]=useState("");
 const [zoom,setZoom]=useState(100);
 const [showDiscovered,setShowDiscovered]=useState(true);
 const [activeNamespace,setActiveNamespace]=useState<string>("ALL");
 const [mapView,setMapView]=useState<"overview"|"detail">("overview");
 const filtered=useMemo(()=>resources.filter(r=>(activeNamespace==="ALL"||r.namespace===activeNamespace)&&(showDiscovered||r.selected)&&[r.kind,r.name,r.namespace,...r.references.map(x=>x.name)].join(" ").toLowerCase().includes(search.toLowerCase())),[resources,activeNamespace,showDiscovered,search]);
 const focused=resources.find(r=>id(r)===focus);
 const covered=coverageKnown;
 const recorded=filtered.reduce((n,r)=>n+r.references.length,0);
 return <section className={styles.mapShell} aria-label="Application dependency topology">
   <header className={styles.mapHeader}>
     <div><span className={styles.mapEyebrow}>APPLICATION DEPENDENCY MAP</span><h3>Discovered application topology</h3><p>Explore selected namespaces, workloads and supporting resources</p></div>
     <div className={styles.mapLegend}><span><i className={styles.mapGreen}/> Included in draft</span><span><i className={styles.mapWhite}/> Discovered</span><span><i className={styles.mapAmber}/> Needs validation</span></div>
   </header>
   <div className={styles.mapToolbar}>
     <div className={styles.mapViewSwitch} role="group" aria-label="Topology map view"><button className={mapView==="overview"?styles.mapViewActive:""} onClick={()=>setMapView("overview")}>Namespace map</button><button className={mapView==="detail"?styles.mapViewActive:""} onClick={()=>setMapView("detail")} disabled={!focused}>Workload detail</button></div>
     <label className={styles.mapSearch}><Search size={15}/><input value={search} onChange={e=>setSearch(e.target.value)} aria-label="Search application map" placeholder="Search workloads or dependencies"/></label>
     <label className={styles.mapToggle}><input type="checkbox" checked={showDiscovered} onChange={e=>setShowDiscovered(e.target.checked)}/> Show discovered</label>
     <div className={styles.mapZoom}><button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(80,z-10))}><ZoomOut size={15}/></button><span>{zoom}%</span><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(120,z+10))}><ZoomIn size={15}/></button><button aria-label="Reset zoom" onClick={()=>setZoom(100)}><RotateCcw size={15}/></button></div>
   </div>
   <div className={styles.mapBody}>
     <aside className={styles.mapSidebar} aria-label="Namespace explorer"><strong>Namespaces <small>{namespaces.length}</small></strong>
       <button aria-current={activeNamespace==="ALL"?"true":undefined} onClick={()=>{setActiveNamespace("ALL");setMapView("overview");}}><Boxes size={17}/><span>All selected namespaces<small>{resources.length} workloads</small></span><ChevronRight size={14}/></button>
       {namespaces.map(ns=><button key={ns} aria-current={activeNamespace===ns?"true":undefined} onClick={()=>{setActiveNamespace(ns);setMapView("overview");}}><Boxes size={17}/><span>{ns}<small>{resources.filter(r=>r.namespace===ns).length} workloads · {resources.filter(r=>r.namespace===ns&&r.selected).length} included</small></span><ChevronRight size={14}/></button>)}
       <div className={styles.mapEvidence}><strong>Evidence status</strong><span>{recorded} recorded references</span><small>{covered?"Reference inventory collected":"Relationship references not collected. A new assessment is needed for verified dependency edges."}</small></div>
     </aside>
     <div className={styles.mapStage}>
       {!covered&&<div className={styles.mapAlert}><AlertTriangle size={17}/><span><strong>Dependency mapping requires reassessment.</strong> Workloads are real discovered objects; no unverified connections are presented as fact.</span></div>}
       <div className={styles.mapStats}><span><strong>{filtered.length}</strong> workloads displayed</span><span><strong>{filtered.filter(r=>r.selected).length}</strong> included</span><span><strong>{recorded}</strong> recorded links</span></div>
       {mapView==="detail" && focused ? <div className={styles.mapFocusCanvas}>
          <div className={styles.mapFocusHeading}><span>WORKLOAD DEPENDENCY VIEW</span><button onClick={()=>setMapView("overview")}>Back to namespace map</button></div>
          <div className={styles.mapFocusLayout}>
            <div className={styles.mapFocusPrimary}><span>{focused.kind} · {focused.namespace}</span><strong>{focused.name}</strong><small>{focused.selected?"Included in migration draft":"Discovered — not included"}</small></div>
            <div className={styles.mapFocusArrow} aria-hidden="true">{focused.references.length>0?"→":"· · ·"}</div>
            <div className={styles.mapFocusRelationships}>
              <strong>Recorded dependency references ({focused.references.length})</strong>
              {focused.references.map((ref,index)=><div key={index} className={ref.present?styles.mapFocusVerified:styles.mapFocusMissing}><GitBranch size={15}/><span><b>{ref.name}</b><small>{ref.kind} · {ref.present?"Present in source inventory":"Missing from source inventory"}</small></span></div>)}
              {focused.references.length===0&&<p>No recorded dependency references are available for this workload. Connections cannot be established from the current evidence.</p>}
              {focused.potentialClaims.length>0&&<div className={styles.mapFocusStorage}><Database size={15}/> Potential storage — requires verification: {focused.potentialClaims.map(x=>x.name).join(", ")}</div>}
            </div>
          </div>
          {!focused.selected&&onSelect&&<button className={styles.mapAdd} disabled={readOnly} onClick={()=>onSelect(focused)}>Add workload to migration draft</button>}
        </div> : <div className={styles.mapScroll}><div className={styles.mapCanvas} style={{zoom:`${zoom}%`}}>
       {namespaces.filter(ns=>(activeNamespace==="ALL"||activeNamespace===ns)&&filtered.some(r=>r.namespace===ns)).map((ns,index)=>{
         const entries=filtered.filter(r=>r.namespace===ns);
         return <section className={styles.mapGroup} data-tone={index%2===0?"blue":"green"} key={ns}>
           <div className={styles.mapGroupHeader}><div><Boxes size={18}/><strong>{ns}</strong><span>{entries.length} workloads</span></div><small>{entries.filter(r=>r.selected).length} included</small></div>
           <div className={styles.mapNodes}>{entries.map(r=><div className={styles.mapUnit} key={id(r)}>
             <button type="button" className={r.selected?styles.mapNodeIncluded:styles.mapNode} onClick={()=>{setFocus(id(r));setMapView("detail");}} aria-label={`Inspect ${r.kind} ${r.name}`}>
               <span className={styles.mapNodeIcon}>{glyph(r.kind)}</span><span className={styles.mapNodeCopy}><strong>{r.name}</strong><small>{r.kind}</small></span>{r.selected&&<CheckCircle2 size={16} className={styles.mapCheck}/>}
             </button>
             {r.references.length>0&&<div className={styles.mapConnections}><div className={styles.mapConnectionStem}/>{r.references.map((ref,i)=><div key={i} className={ref.present?styles.mapRef:styles.mapRefMissing}><GitBranch size={13}/><span><strong>{ref.name}</strong><small>{ref.kind} · {ref.present?"Recorded in inventory":"Missing from inventory"}</small></span></div>)}</div>}
             {r.potentialClaims.length>0&&<div className={styles.mapClaims}><Database size={13}/><span>Storage to verify: {r.potentialClaims.map(c=>c.name).join(", ")}</span></div>}
           </div>)}</div>
         </section>;
       })}
       {!filtered.length&&<p className={styles.mapEmpty}>No workloads match the current filters.</p>}
       </div></div>}
     </div>
   </div>
   <footer className={styles.mapFooter}>Solid connectors represent recorded resource references only. Storage candidates and missing evidence are not verified dependencies.</footer>
   {focused&&mapView==="overview"&&<div className={styles.mapInspector} role="region" aria-label="Resource details"><div><strong>Resource details</strong><button aria-label="Close resource details" onClick={()=>setFocus(null)}>×</button></div><h4>{focused.name}</h4><p>{focused.namespace} · {focused.kind}</p><p>{focused.selected?"Included in the migration draft":"Discovered; not included in the migration draft"}</p><p>{focused.references.length} recorded references · {focused.potentialClaims.length} storage candidates</p>{!focused.selected&&onSelect&&<button className={styles.mapAdd} disabled={readOnly} onClick={()=>{onSelect(focused);setFocus(null)}}>Add to draft</button>}</div>}
 </section>;
}
