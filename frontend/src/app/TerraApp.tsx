import { refreshWorkspace, useWorkspaceState, terra } from '../data/terra';
import type { TransferSelection } from '../lib/matching-presentation';
import { useEffect, useState } from "react";
import { IconBox, IconChartBar, IconClipboardCheck, IconHome, IconRoute, IconTruck, IconUpload } from "@tabler/icons-react";
import type { AppPage } from "./page-types";
import {
  ApprovalsPage,
  ImpactPage,
  MatchingPage,
  MaterialsPage,
  OverviewPage,
  TransfersPage,
  UploadPage,
} from "./pages";
import { rememberActiveOptimisationRun } from "../lib/optimisation-preview";
import "./top-navigation.css";
import "./semantic-colors.css";
import "./terra-app.css";
import "./workspace-ui.css";
import "./terra-visual-restoration.css";
import { pageUrl, readPageTarget, type PageTarget } from "../lib/workspace-presentation";
import { ErrorNotice } from "./components-workspace";

type NavigationItem = {
  id: AppPage;
  label: string;
  group: "core" | "workflow" | "utility";
  icon: typeof IconHome;
};

const navigation: NavigationItem[] = [
  { id: "overview", label: "Home", group: "core", icon: IconHome },
  { id: "materials", label: "Inventory", group: "core", icon: IconBox },
  { id: "matching", label: "Matching", group: "core", icon: IconRoute },
  { id: "approvals", label: "Approvals", group: "workflow", icon: IconClipboardCheck },
  { id: "transfers", label: "Deliveries", group: "workflow", icon: IconTruck },
  { id: "upload", label: "Upload", group: "utility", icon: IconUpload },
  { id: "impact", label: "Report", group: "utility", icon: IconChartBar },
];

export default function TerraApp() {
  const [target, setTarget] = useState<PageTarget>(() => readPageTarget(location.href));
  const [entry,setEntry]=useState(0);
  const [drawerOpen,setDrawerOpen]=useState(false);
  const [projectId,setProjectId]=useState('ALL');
  const page=target.page;
  const workspace=useWorkspaceState();
  useEffect(()=>{const reload=()=>{void refreshWorkspace().catch(()=>{});};reload();window.addEventListener('focus',reload);const timer=setInterval(()=>{if(document.visibilityState==='visible')reload();},4000);return()=>{clearInterval(timer);window.removeEventListener('focus',reload);};},[]);
  useEffect(()=>{setProjectId('ALL');setEntry(n=>n+1);},[workspace.epoch]);
  const navigate=(page:AppPage,details:Omit<PageTarget,'page'>={})=>{
    if(!window.dispatchEvent(new Event('terra:before-editor-navigation',{cancelable:true})))return;
    setProjectId('ALL');const next={page,...details};history.pushState(null,'',pageUrl(next,location.href));setTarget(next);setEntry(n=>n+1);window.scrollTo(0,0);void refreshWorkspace().catch(()=>{});
  };
  useEffect(()=>{const back=()=>{if(!window.dispatchEvent(new Event('terra:before-editor-navigation',{cancelable:true}))){history.pushState(null,'',pageUrl(target,location.href));return;}setTarget(readPageTarget(location.href));setEntry(n=>n+1);window.scrollTo(0,0);};window.addEventListener('popstate',back);return()=>window.removeEventListener('popstate',back);},[target]);
  const sidebar=(next:AppPage)=>navigate(next);
  const openPersistedPlan=(runId:string,transfer?:TransferSelection)=>{rememberActiveOptimisationRun(runId);navigate('approvals',{runId,supplyId:transfer?.supply_offer_id,demandId:transfer?.demand_request_id});};
  if (!workspace.ready) return <main className="terra-page-section" role="status"><h1>Terra</h1><p>{workspace.error || 'Loading current project and material data…'}</p>{workspace.error && <button onClick={() => void refreshWorkspace().catch(() => {})}>Retry loading Terra</button>}</main>;

  return <div className={`terra-side-shell terra-top-shell workspace-ui terra-restored ${drawerOpen?'is-drawer-open':''}`}>
    <aside className="terra-side-navigation" onMouseEnter={()=>setDrawerOpen(true)} onMouseLeave={()=>setDrawerOpen(false)} onFocusCapture={()=>setDrawerOpen(true)} onBlurCapture={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node|null))setDrawerOpen(false);}}>
      <button className="terra-side-brand" type="button" onClick={()=>sidebar('overview')} aria-label="Terra home"><img src="/terra-wordmark.png" alt="Terra"/></button>
      <nav aria-label="Terra workspace sections">{navigation.map(item=>{const Icon=item.icon;return <button className={`terra-side-link terra-side-link--${item.group} ${item.id===page?'is-active':''}`} key={item.id} type="button" aria-label={item.label} aria-current={item.id===page?'page':undefined} onClick={()=>sidebar(item.id)}><Icon aria-hidden="true"/><span>{item.label}</span></button>;})}</nav>
      <div className="workspace-operator"><span className="restored-operator-mark" aria-hidden="true">TO</span><span className="restored-operator-name">Operator</span></div>
    </aside>
    <div className="terra-side-content"><main key={`${workspace.epoch}:${entry}`}>
      {workspace.error&&<ErrorNotice error={workspace.error}><button onClick={()=>void refreshWorkspace().catch(()=>{})}>Retry connection</button></ErrorNotice>}
      {page==='overview'&&<OverviewPage projectId={projectId} onProjectChange={setProjectId} navigate={navigate}/>}
      {page==='materials'&&<MaterialsPage projectId={projectId} onProjectChange={setProjectId} onAdd={()=>navigate('upload')}/>}
      {page==='matching'&&<MatchingPage reset={!target.resume&&!target.materialId} initialMaterial={target.materialId} onPlanPersisted={openPersistedPlan}/>}
      {page==='approvals'&&<ApprovalsPage connected={!workspace.error} runId={target.runId||''} transferSelection={target.supplyId&&target.demandId?{supply_offer_id:target.supplyId,demand_request_id:target.demandId}:undefined} onMatching={()=>navigate('matching',{resume:true})} onDelivery={id=>navigate('transfers',{transferId:id})}/>}
      {page==='transfers'&&<TransfersPage projectId={projectId} onProjectChange={setProjectId} initialTransfer={target.transferId} onMatching={()=>navigate('matching')} onReport={(project,transfer)=>navigate('impact',{projectId:project,transferId:transfer})}/>}
      {page==='upload'&&<UploadPage resume={target.resume} onMatching={()=>navigate('matching')}/>}
      {page==='impact'&&<ImpactPage projectId={target.projectId||'ALL'} initialTransfer={target.transferId}/>}
    </main></div>
  </div>;
}
