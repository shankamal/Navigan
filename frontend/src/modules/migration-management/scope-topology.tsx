"use client";
import {useEffect,useMemo,useState} from "react";
import {AlertTriangle,Boxes,CheckCircle2,Database,Layers3,Network,Search,ZoomIn,ZoomOut,RotateCcw,GitBranch,ChevronRight} from "lucide-react";
import styles from "./scope-topology.module.css";
export type TopologyResource={kind:string;namespace:string|null;name:string;selected:boolean;references:{kind:string;name:string;present:boolean}[];potentialClaims:{name:string}[]};
type SupportResource={kind:string;namespace:string|null;name:string;selected:boolean};
type Props={namespaces:string[];resources:TopologyResource[];supportingResources?:SupportResource[];coverageKnown:boolean;onSelect?:(resource:TopologyResource)=>void;readOnly?:boolean};
const id=(r:TopologyResource)=>[r.namespace,r.kind,r.name].join("/");
const scopedCount=(resources:SupportResource[],ns:string)=>resources.filter(r=>r.selected&&(ns==="ALL"||r.namespace===ns)).length;
function glyph(kind:string){return kind==="StatefulSet"?<Database size={16}/>:kind==="Service"?<Network size={16}/>:<Layers3 size={16}/>;}
export function ScopeTopology({namespaces,resources,supportingResources=[],coverageKnown,onSelect,readOnly}:Props){
 const [focus,setFocus]=useState<string|null>(null);
 const [search,setSearch]=useState("");
 const [zoom,setZoom]=useState(100);
 const [showDiscovered,setShowDiscovered]=useState(true);
 const [activeNamespace,setActiveNamespace]=useState<string>("ALL");
 const [mapView,setMapView]=useState<"overview"|"detail">("overview");
 const filtered=useMemo(()=>resources.filter(r=>(activeNamespace==="ALL"||r.namespace===activeNamespace)&&(showDiscovered||r.selected)&&[r.kind,r.name,r.namespace,...r.references.map(x=>x.name)].join(" ").toLowerCase().includes(search.toLowerCase())),[resources,activeNamespace,showDiscovered,search]);
 const [showSupporting,setShowSupporting]=useState(false);
 const focused=resources.find(r=>id(r)===focus && namespaces.includes(r.namespace??""));
 useEffect(()=>{if(activeNamespace!=="ALL"&&!namespaces.includes(activeNamespace)){setActiveNamespace("ALL");setMapView("overview");setFocus(null);}},[activeNamespace,namespaces]);
 useEffect(()=>{if(mapView==="detail"&&!focused)setMapView("overview");},[mapView,focused]);
 const covered=coverageKnown;
 const recorded=filtered.reduce((n,r)=>n+r.references.length,0);
 const visibleRecorded=coverageKnown?recorded:0;
 const selectedWorkloadCount=filtered.filter(r=>r.selected).length;
 const selectedSupportCount=scopedCount(supportingResources.filter(r=>namespaces.includes(r.namespace??"")),activeNamespace);
 const scopedSupporting=supportingResources.filter(r=>namespaces.includes(r.namespace??"")&&(activeNamespace==="ALL"||r.namespace===activeNamespace)&&(!search||[r.kind,r.name,r.namespace].join(" ").toLowerCase().includes(search.toLowerCase())));
 const supportCategories=[{label:"Networking",kinds:["Service","Ingress","NetworkPolicy"]},{label:"Configuration & identity",kinds:["ConfigMap","Secret","ServiceAccount"]},{label:"Data & storage",kinds:["PersistentVolumeClaim"]}];
 return <section className={styles.mapShell} aria-label="Application dependency topology">
   <header className={styles.mapHeader}>
     <div><span className={styles.mapEyebrow}>APPLICATION DEPENDENCY MAP</span><h3>Discovered application topology</h3><p>Explore selected namespaces, workloads and supporting resources</p></div>
     <div className={styles.mapLegend}><span><i className={styles.mapGreen}/> Included in draft</span><span><i className={styles.mapWhite}/> Discovered</span><span><i className={styles.mapAmber}/> Needs validation</span></div>
   </header>
   <div className={styles.mapToolbar}>
     <div className={styles.mapViewSwitch} role="group" aria-label="Topology map view"><button className={mapView==="overview"?styles.mapViewActive:""} onClick={()=>setMapView("overview")}>Namespace map</button><button className={mapView==="detail"?styles.mapViewActive:""} onClick={()=>setMapView("detail")} disabled={!focused}>Workload detail</button></div>
     <label className={styles.mapSearch}><Search size={15}/><input value={search} onChange={e=>setSearch(e.target.value)} aria-label="Search application map" placeholder="Search workloads or dependencies"/></label>
     <label className={styles.mapToggle}><input type="checkbox" checked={showSupporting} onChange={e=>setShowSupporting(e.target.checked)}/> Show supporting resources</label><label className={styles.mapToggle}><input type="checkbox" checked={showDiscovered} onChange={e=>setShowDiscovered(e.target.checked)}/> Show discovered</label>
     <div className={styles.mapZoom}><button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(80,z-10))}><ZoomOut size={15}/></button><span>{zoom}%</span><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(120,z+10))}><ZoomIn size={15}/></button><button aria-label="Reset zoom" onClick={()=>setZoom(100)}><RotateCcw size={15}/></button></div>
   </div>
   <div className={styles.mapBody}>
     <aside className={styles.mapSidebar} aria-label="Namespace explorer"><strong>Namespaces <small>{namespaces.length}</small></strong>
       <button aria-current={activeNamespace==="ALL"?"true":undefined} onClick={()=>{setActiveNamespace("ALL");setMapView("overview");setFocus(null);}}><Boxes size={17}/><span>All selected namespaces<small>{resources.length} workloads</small></span><ChevronRight size={14}/></button>
       {namespaces.map(ns=><button key={ns} aria-current={activeNamespace===ns?"true":undefined} onClick={()=>{setActiveNamespace(ns);setMapView("overview");setFocus(null);}}><Boxes size={17}/><span>{ns}<small>{resources.filter(r=>r.namespace===ns).length} workloads · {resources.filter(r=>r.namespace===ns&&r.selected).length} included</small></span><ChevronRight size={14}/></button>)}
       <div className={styles.mapEvidence}><strong>Evidence status</strong><span>{visibleRecorded} recorded references</span><small>{covered?"Reference inventory collected":"Relationship references not collected. A new assessment is needed for verified dependency edges."}</small></div>
     </aside>
     <div className={styles.mapStage}>
       {!covered&&<div className={styles.mapAlert}><AlertTriangle size={17}/><span><strong>Dependency mapping requires reassessment.</strong> Workloads are real discovered objects; no unverified connections are presented as fact.</span></div>}
       <div className={styles.mapStats}><span><strong>{filtered.length}</strong> workloads displayed</span><span><strong>{selectedWorkloadCount}</strong> workloads included</span><span><strong>{selectedSupportCount}</strong> supporting resources in draft</span><span><strong>{visibleRecorded}</strong> recorded references</span><span><strong>{scopedSupporting.length}</strong> supporting resources</span></div>
       {mapView==="detail" && focused ? <div className={styles.mapFocusCanvas}>
          <div className={styles.mapFocusHeading}><span>WORKLOAD DEPENDENCY VIEW</span><button onClick={()=>setMapView("overview")}>Back to namespace map</button></div>
          <div className={styles.mapFocusLayout}>
            <div className={styles.mapFocusPrimary}><span>{focused.kind} · {focused.namespace}</span><strong>{focused.name}</strong><small>{focused.selected?"Included in migration draft":"Discovered — not included"}</small></div>
            <div className={styles.mapFocusArrow} aria-hidden="true">{covered&&focused.references.length>0?"→":"?"}</div>
            <div className={styles.mapFocusRelationships}>
              <strong>Recorded dependency references ({covered?focused.references.length:0})</strong>
              {covered&&focused.references.map((ref,index)=><div key={index} className={ref.present?styles.mapFocusVerified:styles.mapFocusMissing}><GitBranch size={15}/><span><b>{ref.name}</b><small>{ref.kind} · {ref.present?"Present in source inventory":"Missing from source inventory"}</small></span></div>)}
              {(!covered||focused.references.length===0)&&<p>{!covered?"Relationship evidence was not collected in this assessment; reassess to discover references.":"No explicit dependency references were recorded for this workload."}</p>}
              {focused.potentialClaims.length>0&&<div className={styles.mapFocusStorage}><Database size={15}/> Potential storage — requires verification: {focused.potentialClaims.map(x=>x.name).join(", ")}</div>}
            </div>
          </div>
          {!focused.selected&&onSelect&&<button className={styles.mapAdd} disabled={readOnly} onClick={()=>onSelect(focused)}>Add workload to migration draft</button>}
        </div> : <div className={styles.mapScroll}><div className={styles.mapCanvas} style={{zoom:`${zoom}%`}}>
       {namespaces.filter(ns=>(activeNamespace==="ALL"||activeNamespace===ns)&&filtered.some(r=>r.namespace===ns)).map((ns,index)=>{
         const entries=filtered.filter(r=>r.namespace===ns);
         return <section className={styles.mapGroup} data-tone={index%2===0?"blue":"green"} key={ns}>
           <div className={styles.mapGroupHeader}><div><Boxes size={18}/><strong>{ns}</strong><span>{entries.length} workloads</span></div><small>{entries.filter(r=>r.selected).length} included</small></div>
           <div className={styles.graphTopology}>
             {!covered?<div className={styles.graphCompact}>
               <div className={styles.graphCompactHeading}><span>DISCOVERED WORKLOADS</span><span>Choose a workload to review its dependencies and migration readiness</span></div>
               <div className={styles.graphCompactGrid}>{entries.map(r=><button type="button" key={id(r)} className={r.selected?styles.graphCompactSelected:styles.graphCompactNode} onClick={()=>{setFocus(id(r));setMapView("detail");}} aria-label={`Inspect ${r.kind} ${r.name}`}>
                 <span className={styles.mapNodeIcon}>{glyph(r.kind)}</span>
                 <span className={styles.mapNodeCopy}><strong>{r.name}</strong><small>{r.kind} · {r.selected?"Included in draft":"Discovered"}</small></span>
                 {r.selected&&<CheckCircle2 size={16} className={styles.mapCheck}/>}
               </button>)}</div>
             </div>:<>
             <div className={styles.graphColumnHead}><span>APPLICATION WORKLOADS</span><span>RECORDED DEPENDENCIES</span></div>
             <div className={styles.graphRows}>{entries.map(r=>{
               const observed=covered?r.references:[];
               return <div className={styles.graphRow} key={id(r)}>
                 <button type="button" className={r.selected?styles.graphWorkloadSelected:styles.graphWorkload} onClick={()=>{setFocus(id(r));setMapView("detail");}} aria-label={`Inspect ${r.kind} ${r.name}`}>
                   <span className={styles.mapNodeIcon}>{glyph(r.kind)}</span>
                   <span className={styles.mapNodeCopy}><strong>{r.name}</strong><small>{r.kind} · {r.selected?"Included in draft":"Discovered"}</small></span>
                   {r.selected&&<CheckCircle2 size={16} className={styles.mapCheck}/>}
                 </button>
                 <div className={observed.some(ref=>ref.present)?styles.graphEdge:observed.length?styles.graphEdgeMissing:styles.graphEdgeUnknown} aria-hidden="true"><span/></div>
                 <div className={styles.graphDependencyArea}>
                   {observed.length?observed.map((ref,i)=>{
                     const match=scopedSupporting.find(candidate=>candidate.kind===ref.kind&&candidate.name===ref.name&&candidate.namespace===r.namespace);
                     return <div key={i} className={ref.present?styles.graphDependency:styles.graphDependencyMissing}>
                       <span className={styles.graphDepGlyph}>{ref.kind==="PersistentVolumeClaim"?<Database size={15}/>:<Network size={15}/>}</span>
                       <span><strong>{ref.name}</strong><small>{ref.kind} · {ref.present?"Recorded reference":"Not in inventory"}{match?.selected?" · Included":""}</small></span>
                     </div>;
                   }):<div className={styles.graphNoEvidence}>{covered?"No explicit resource references recorded":"Dependencies not collected"}{r.potentialClaims.length>0&&<small>Potential storage: {r.potentialClaims.map(c=>c.name).join(", ")} · unverified</small>}</div>}
                 </div>
               </div>;
             })}</div>
             </>}
           </div>
         </section>;
       })}
       {showSupporting&&scopedSupporting.length>0&&<section className={styles.mapSupportPanel} aria-label="Supporting resources in selected namespace scope">
          <div className={styles.mapSupportHeading}><strong>Supporting resources</strong><span>{scopedSupporting.length} discovered objects · Inclusion is not proof of workload dependency</span></div>
          <div className={styles.mapSupportGrid}>{supportCategories.map(group=>{
            const items=scopedSupporting.filter(r=>group.kinds.includes(r.kind));
            return <div className={styles.mapSupportCategory} key={group.label}><div><strong>{group.label}</strong><span>{items.length}</span></div>
              {items.map(r=><div className={r.selected?styles.mapSupportIncluded:styles.mapSupportItem} key={[r.namespace,r.kind,r.name].join("/")}>
                <span><b>{r.name}</b><small>{r.kind} · {r.namespace}</small></span><small>{r.selected?"In draft":"Discovered"}</small>
              </div>)}
              {!items.length&&<p>No resources discovered</p>}
            </div>;
          })}</div>
        </section>}
       {!filtered.length&&<p className={styles.mapEmpty}>No workloads match the current filters.</p>}
       </div></div>}
     </div>
   </div>
   <footer className={styles.mapFooter}>Connectors appear only when the assessment provides relationship-reference coverage. Storage candidates and missing evidence are not verified dependencies.</footer>
   {focused&&mapView==="overview"&&<div className={styles.mapInspector} role="region" aria-label="Resource details"><div><strong>Resource details</strong><button aria-label="Close resource details" onClick={()=>setFocus(null)}>×</button></div><h4>{focused.name}</h4><p>{focused.namespace} · {focused.kind}</p><p>{focused.selected?"Included in the migration draft":"Discovered; not included in the migration draft"}</p><p>{focused.references.length} recorded references · {focused.potentialClaims.length} storage candidates</p>{!focused.selected&&onSelect&&<button className={styles.mapAdd} disabled={readOnly} onClick={()=>{onSelect(focused);setFocus(null)}}>Add to draft</button>}</div>}
 </section>;
}
