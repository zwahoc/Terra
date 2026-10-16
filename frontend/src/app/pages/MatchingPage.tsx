import { useEffect, useMemo, useState } from "react";
import StatusBadge from "../../components/StatusBadge";
import { materialName, terra } from "../../data/terra";
import { currentPlanningDate, getOptimisationPreview, persistOptimisationRun, type OptimisationObjective, type OptimisationPreview } from "../../lib/optimisation-preview";
import "./matching-redesign.css";

const objectives: { id: OptimisationObjective; label: string }[] = [
  { id: "MAX_REUSE", label: "Maximise reuse" },
  { id: "EARLIEST_DEADLINE", label: "Earliest deadline" },
  { id: "MAX_NET_CO2E_AVOIDED", label: "Estimated carbon" },
];

type MatchingStep = "projects" | "materials" | "details";
const formatDate = (value?: string) => value ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${value}T00:00:00`)) : "Not available";

export default function MatchingPage({ onPlanPersisted }: { onPlanPersisted: (runId: string) => void }) {
  const planningDate = useMemo(() => currentPlanningDate(), []);
  const [step, setStep] = useState<MatchingStep>("projects");
  const [objective, setObjective] = useState<OptimisationObjective>("MAX_REUSE");
  const [projectId, setProjectId] = useState("");
  const [demandId, setDemandId] = useState("");
  const [preview, setPreview] = useState<OptimisationPreview | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    if (!projectId) { setPreview(null); setState("idle"); return () => { active = false; }; }
    setState("loading");
    // Keep one global plan so constrained supply cannot be proposed to two projects.
    getOptimisationPreview(objective, planningDate).then((result) => {
      if (!active) return;
      setPreview(result); setState("ready");
    }).catch((error: unknown) => {
      if (!active) return;
      setMessage(error instanceof Error ? error.message : "Matching is unavailable."); setState("error");
    });
    return () => { active = false; };
  }, [objective, planningDate, projectId]);

  const project = terra.projects.find((item) => item.id === projectId);
  const demands = useMemo(() => terra.demand_requests.filter((item) => item.destination_project_id === projectId && item.request_status === "OPEN"), [projectId]);
  const allocations = useMemo(() => preview?.plan.allocations.filter((item) => demands.some((demand) => demand.id === item.demand_request_id)) ?? [], [preview, demands]);
  const allocationsByDemand = useMemo(() => {
    const grouped = new Map<string, OptimisationPreview["plan"]["allocations"]>();
    allocations.forEach((item) => grouped.set(item.demand_request_id, [...(grouped.get(item.demand_request_id) ?? []), item]));
    return grouped;
  }, [allocations]);
  const demand = demands.find((item) => item.id === demandId);
  const selectedAllocations = demand ? allocationsByDemand.get(demand.id) ?? [] : [];
  const forecastByAllocation = useMemo(() => new Map((preview?.forecast_previews ?? []).map((item) => [`${item.supply_offer_id}:${item.demand_request_id}`, item])), [preview]);
  const stepIndex = ["projects", "materials", "details"].indexOf(step);

  const chooseProject = (id: string) => { setProjectId(id); setDemandId(""); setStep("materials"); };
  const sendToApprovals = async () => {
    if (!preview || saving) return;
    setSaving(true); setMessage("");
    try {
      const persisted = await persistOptimisationRun(objective, planningDate);
      onPlanPersisted(persisted.run.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Terra could not send this plan to Approvals.");
    } finally {
      setSaving(false);
    }
  };

  return <div className="matching-flow">
    <header className="matching-flow__header"><div><h1>Matching</h1><span>Choose a project and inspect proposed material reuse before sending it for approval.</span></div><small>{formatDate(planningDate)}</small></header>
    <ol className="matching-flow__steps" aria-label="Matching workflow">{["Project", "Materials", "Details"].map((label, index) => <li key={label} className={index === stepIndex ? "is-current" : index < stepIndex ? "is-complete" : ""}><span>{index + 1}</span>{label}</li>)}</ol>

    {step === "projects" && <section className="matching-stage matching-project-stage"><header><h2>Choose a project</h2><span>Open the current matching result for its outstanding material needs.</span></header><div className="matching-project-grid">{terra.projects.map((item) => { const projectDemands = terra.demand_requests.filter((demandItem) => demandItem.destination_project_id === item.id && demandItem.request_status === "OPEN"); const openDemands = projectDemands.length; const requiredQuantity = projectDemands.reduce((total, demandItem) => total + demandItem.required_quantity, 0); return <button key={item.id} type="button" onClick={() => chooseProject(item.id)}><span>{item.id}</span><strong>{item.name}</strong><small>{openDemands} open demand{openDemands === 1 ? "" : "s"} · {requiredQuantity.toLocaleString()} pcs</small><b>Open plan</b></button>; })}</div></section>}

    {step !== "projects" && <>
      <section className="matching-flow__project-bar"><button className="matching-back-link" type="button" onClick={() => setStep(step === "details" ? "materials" : "projects")}>‹ {step === "details" ? "Materials" : "Projects"}</button><div><span>Project</span><b>{project?.name ?? projectId}</b></div><label>Priority<select value={objective} onChange={(event) => setObjective(event.target.value as OptimisationObjective)}>{objectives.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></section>
      {state === "loading" && <div className="matching-empty matching-loader" role="status"><div className="newtons-cradle" aria-hidden="true"><i className="newtons-cradle__dot" /><i className="newtons-cradle__dot" /><i className="newtons-cradle__dot" /><i className="newtons-cradle__dot" /></div><div><b>Preparing plan</b><span>Checking supply, timing and carbon data.</span></div></div>}
      {state === "error" && <div className="matching-empty"><b>Matching is unavailable</b><span>{message}</span></div>}
      {state === "ready" && step === "materials" && <section className="matching-stage matching-material-stage"><header><div><p>Materials</p><h2>Material plan</h2><span>Review the proposed quantities for this project.</span></div></header><div className="matching-demand-list">{demands.map((item) => { const lines = allocationsByDemand.get(item.id) ?? []; const proposed = lines.reduce((sum, line) => sum + line.proposed_quantity, 0); const coverageSummary = preview?.matching_coverage_by_demand?.[item.id]; const coverageStatus = coverageSummary?.status ?? (proposed >= item.required_quantity ? "COVERED" : proposed > 0 ? "PARTIALLY_COVERED" : "NOT_COVERED"); const coverage = coverageStatus.replaceAll("_", " ").toLowerCase().replace(/^./, (letter) => letter.toUpperCase()); return <button type="button" key={item.id} onClick={() => { setDemandId(item.id); setStep("details"); }}><div><span>{item.id}</span><strong>{materialName(item.material_id)}</strong><small>Need by {formatDate(item.required_by)}</small></div><div className="matching-demand-list__metrics"><b>{item.required_quantity.toLocaleString()} needed</b><b>{proposed.toLocaleString()} proposed</b><em className={coverageStatus === "COVERED" ? "" : "is-gap"}>{coverage}</em></div><i>Details</i></button>; })}</div></section>}
      {state === "ready" && step === "details" && demand && <section className="matching-stage matching-detail-stage"><header><p>Details</p><h2>{materialName(demand.material_id)}</h2><span>{demand.required_quantity.toLocaleString()} pcs needed by {formatDate(demand.required_by)}</span></header>{selectedAllocations.length ? <div className="matching-allocation-evidence">{selectedAllocations.map((item) => { const forecast = forecastByAllocation.get(`${item.supply_offer_id}:${item.demand_request_id}`); const matchReasons = item.reason_codes.filter((reason) => !reason.endsWith("_OPTIMUM") && reason !== "PAIR_PRIORITY_TIE_BREAK"); return <article key={`${item.supply_offer_id}:${item.demand_request_id}`}><div className="matching-option__top"><div><span>{item.supply_offer_id} to {item.demand_request_id}</span><h3>{item.proposed_quantity.toLocaleString()} {item.unit} proposed</h3><p>Recommended supply</p></div><StatusBadge status="PENDING" displayLabel="Approval required" /></div><dl><div><dt>Available</dt><dd>{formatDate(item.earliest_delivery_date)}</dd></div><div><dt>Need by</dt><dd>{formatDate(item.required_by)}</dd></div><div><dt>Priority</dt><dd>{preview?.plan.objective.replaceAll("_", " ")}</dd></div><div><dt>Carbon forecast</dt><dd>{forecast?.net_avoided_kgco2e ? `${Number(forecast.net_avoided_kgco2e).toLocaleString(undefined, { maximumFractionDigits: 2 })} kgCO2e` : "Evidence incomplete"}</dd></div></dl><section className="matching-match-reason"><span>Why this match</span><p>{matchReasons.map((reason) => reason.replaceAll("_", " ").toLowerCase()).join(" · ") || "Eligible supply and demand pairing"}</p></section></article>; })}</div> : <div className="matching-empty"><b>No material proposed</b><span>No suitable supply is included in this plan.</span></div>}<footer className="matching-stage__actions"><div><span>Proposed for this project</span><b>{allocations.reduce((sum, item) => sum + item.proposed_quantity, 0).toLocaleString()} pcs</b><small>Stock remains unreserved</small></div><button type="button" disabled={saving || !preview?.plan.allocations.length} onClick={sendToApprovals}>{saving ? "Opening…" : "View Approvals"}</button></footer>{message && <p className="terra-workflow-message" role="status">{message}</p>}</section>}
    </>}
  </div>;
}
