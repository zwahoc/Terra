import { useEffect, useState } from "react";
import StatusBadge from "../../components/StatusBadge";
import { materialName, terra } from "../../data/terra";
import { downloadImpactCsv, listImpactAssessments, type ImpactAssessment } from "../../lib/terra-api";
import "./impact-reporting.css";

type ImpactPageProps = { projectId: string };
const value = (number: number | null) => number === null ? "Incomplete" : `${number.toLocaleString(undefined, { maximumFractionDigits: 2 })} kgCO2e`;
const dateTime = (value: string) => new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

export default function ImpactPage({ projectId: _projectId }: ImpactPageProps) {
  const [assessments, setAssessments] = useState<ImpactAssessment[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [selectedProject, setSelectedProject] = useState("");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    listImpactAssessments().then((rows) => {
      setAssessments(rows);
      setSelectedId((current) => current ?? rows.find((row) => row.basis === "ACTUAL_CONFIRMED_USE")?.id ?? null);
      setState("ready");
    }).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "Impact data is unavailable.");
      setState("error");
    });
  }, []);

  const actual = assessments.filter((assessment) => assessment.basis === "ACTUAL_CONFIRMED_USE");
  const projectActual = actual.filter((assessment) => belongsToProject(assessment, selectedProject));
  const selected = projectActual.find((assessment) => assessment.id === selectedId) ?? projectActual[0];
  const exportActual = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await downloadImpactCsv({ projectId: selectedProject });
      setMessage("Downloaded the selected project report CSV.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Export is unavailable."); }
    finally { setExporting(false); }
  };

  if (state === "ready" && !selectedProject) return <ProjectList actual={actual} chooseProject={setSelectedProject} />;

  return <section className="terra-page-section"><header className="terra-intro"><p>Report</p><h1>Material carbon report</h1><span>Select a material to inspect its confirmed-use carbon estimate.</span></header>{message && <p className="terra-workflow-message" role="status">{message}</p>}<section className="terra-impact"><header className="terra-impact-actions"><button className="terra-report-back" type="button" onClick={() => { setSelectedProject(""); setSelectedId(null); }}>‹ Projects</button><div><span>Selected project</span><h2>{projectActual.length} material record{projectActual.length === 1 ? "" : "s"}</h2></div><button className="terra-download-button" type="button" onClick={exportActual} disabled={state !== "ready" || projectActual.length === 0 || exporting}><span className="terra-download-button__text">{exporting ? "Preparing…" : "Export CSV"}</span><span className="terra-download-button__icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v11m0 0 4-4m-4 4-4-4M5 19h14" /></svg></span></button></header>{state === "loading" && <div className="terra-empty">Loading current impact assessments from Terra.</div>}{state === "error" && <div className="terra-empty">{message}</div>}{state === "ready" && <section className="terra-impact-workbench"><section className="terra-impact-material-list"><header><span>Confirmed-use materials</span><b>{projectActual.length}</b></header>{projectActual.map((item) => <button type="button" className={`terra-impact-material-row ${item.id === selected?.id ? "is-selected" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><div><span>{item.transfer_id ?? item.id}</span><strong>{assessmentMaterialName(item)}</strong><small>{item.quantity_assessed.toLocaleString()} {item.unit} confirmed use</small></div><b>{value(item.net_avoided_kgco2e)}</b></button>)}{!projectActual.length && <div className="terra-empty">No confirmed-use calculation is available for this project.</div>}</section><aside className="terra-impact-preview">{selected ? <ActualUseReport item={selected} /> : <div className="terra-empty">Select a material to view its carbon estimate.</div>}</aside></section>}</section></section>;
}

function ProjectList({ actual, chooseProject }: { actual: ImpactAssessment[]; chooseProject: (id: string) => void }) {
  return <section className="terra-page-section"><header className="terra-intro"><p>Report</p><h1>Choose a project</h1><span>Open confirmed material-use reports for one project.</span></header><section className="terra-impact-group terra-report-project-list">{terra.projects.map((project) => {
    const count = actual.filter((assessment) => belongsToProject(assessment, project.id)).length;
    return <button type="button" className="terra-impact-choice" key={project.id} onClick={() => chooseProject(project.id)}><span>{project.id}</span><strong>{project.name}</strong><small>{count} confirmed-use report{count === 1 ? "" : "s"}</small><b>View reports</b></button>;
  })}</section></section>;
}

function proposalFor(assessment: ImpactAssessment) {
  const transfer = terra.transfers.find((item) => item.id === assessment.transfer_id);
  return transfer && terra.allocation_proposals.find((item) => item.id === transfer.proposal_id);
}

function belongsToProject(assessment: ImpactAssessment, projectId: string) {
  if (!projectId) return true;
  const proposal = proposalFor(assessment);
  const supply = proposal && terra.supply_offers.find((item) => item.id === proposal.supply_offer_id);
  const demand = proposal && terra.demand_requests.find((item) => item.id === proposal.demand_request_id);
  return supply?.source_project_id === projectId || demand?.destination_project_id === projectId;
}

function assessmentMaterialName(assessment: ImpactAssessment) {
  const proposal = proposalFor(assessment);
  const supply = proposal && terra.supply_offers.find((item) => item.id === proposal.supply_offer_id);
  const demand = proposal && terra.demand_requests.find((item) => item.id === proposal.demand_request_id);
  return materialName(supply?.material_id ?? demand?.material_id ?? "Material");
}

function ActualUseReport({ item }: { item: ImpactAssessment }) {
  const missing = Array.isArray(item.assumptions.missing_data) ? item.assumptions.missing_data.join(", ") : "None recorded";
  return <article className="terra-actual-report"><header><div><span>Selected material</span><h2>{assessmentMaterialName(item)}</h2><p>{item.transfer_id ?? "Transfer not linked"} · {item.quantity_assessed.toLocaleString()} {item.unit} confirmed</p></div><StatusBadge status={item.calculation_status} /></header><div className="terra-actual-report__headline"><div><span>Estimated avoided emissions</span><strong>{value(item.net_avoided_kgco2e)}</strong></div></div><dl><div><dt>Avoided new-material production</dt><dd>{value(item.avoided_production_kgco2e)}</dd></div><div><dt>Additional transport</dt><dd>{value(item.additional_transport_kgco2e)}</dd></div><div><dt>Additional processing</dt><dd>{value(item.additional_processing_kgco2e)}</dd></div><div><dt>Evidence state</dt><dd>{item.calculation_status === "INSUFFICIENT_DATA" ? `Missing: ${missing}` : "Complete"}</dd></div></dl><small className="terra-impact-calculated">Calculated {dateTime(item.calculated_at)}</small></article>;
}
