import { useCallback, useEffect, useMemo, useState } from "react";
import StatusBadge from "../../components/StatusBadge";
import { materialName, projectName, terra } from "../../data/terra";
import { getPersistedOptimisationRun, type PersistedAllocationProposal } from "../../lib/optimisation-preview";
import { approveAllocationProposal, listTransfers, type Transfer } from "../../lib/terra-api";
import "./approvals.css";
import "./workflow-listing.css";

type ApprovalStep = "projects" | "materials" | "review";
const projectFor = (proposal: PersistedAllocationProposal) => terra.demand_requests.find((item) => item.id === proposal.demand_request_id)?.destination_project_id ?? "UNASSIGNED";

export default function ApprovalsPage({ runId }: { runId: string }) {
  const [proposals, setProposals] = useState<PersistedAllocationProposal[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [step, setStep] = useState<ApprovalStep>("projects");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!runId) { setProposals([]); setTransfers([]); setState("ready"); return; }
    setState("loading");
    try {
      const [savedRun, currentTransfers] = await Promise.all([getPersistedOptimisationRun(runId), listTransfers()]);
      setProposals(savedRun.proposals); setTransfers(currentTransfers); setState("ready");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Approval proposals are unavailable."); setState("error");
    }
  }, [runId]);

  useEffect(() => { void load(); }, [load]);

  const requests = useMemo(() => proposals.filter((proposal) => proposal.status === "SELECTED" && proposal.compatibility_result === "ELIGIBLE" && !transfers.some((transfer) => transfer.proposal_id === proposal.id)), [proposals, transfers]);
  const projectIds = useMemo(() => [...new Set(requests.map(projectFor))], [requests]);
  const projectRequests = requests.filter((proposal) => projectFor(proposal) === selectedProjectId);
  const selected = projectRequests.find((proposal) => proposal.id === selectedId) ?? projectRequests[0];
  const offer = selected && terra.supply_offers.find((item) => item.id === selected.supply_offer_id);
  const demand = selected && terra.demand_requests.find((item) => item.id === selected.demand_request_id);
  const stepIndex = ["projects", "materials", "review"].indexOf(step);
  const openProject = (id: string) => { setSelectedProjectId(id); setSelectedId(requests.find((proposal) => projectFor(proposal) === id)?.id ?? ""); setStep("materials"); };
  const openReview = (proposalId: string) => { setSelectedId(proposalId); setStep("review"); };
  const approve = async () => {
    if (!selected) return;
    setBusy(true); setMessage("");
    try {
      const transfer = await approveAllocationProposal(selected.id);
      setMessage(`${selected.id} was approved and ${transfer.id} is now requested. Reserve it in Deliveries when ready.`);
      await load(); setStep("projects");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Terra could not approve this proposal.");
    } finally { setBusy(false); }
  };

  return <section className="terra-approval-page"><section className="terra-approval-intro"><p>Approvals</p><h1>Approve matching proposals</h1><span>Work from destination project to material, then confirm one release request.</span></section>{message && <p className="terra-workflow-message" role="status">{message}</p>}{state === "loading" && <section className="terra-approval-detail terra-approval-empty"><h2>Loading proposals</h2></section>}{state === "error" && <section className="terra-approval-detail terra-approval-empty"><h2>Proposals unavailable</h2><p>{message}</p></section>}{state === "ready" && !runId && <section className="terra-approval-detail terra-approval-empty"><h2>No matching plan sent</h2><p>View Approvals from the material details screen after matching.</p></section>}{state === "ready" && runId && <>{step === "projects" && <section className="terra-approval-workbench"><header><h2>Choose a destination project</h2><span>Each project contains only its matching material proposals.</span></header><div className="terra-approval-list" aria-label="Projects awaiting approval">{projectIds.map((id) => { const projectProposals = requests.filter((proposal) => projectFor(proposal) === id); const count = projectProposals.length; const proposedQuantity = projectProposals.reduce((total, proposal) => total + proposal.proposed_quantity, 0); return <button type="button" key={id} onClick={() => openProject(id)}><div><span>{id}</span><strong>{id === "UNASSIGNED" ? "Unassigned project" : projectName(id)}</strong><small>{count} coordinated material {count === 1 ? "proposal" : "proposals"} · {proposedQuantity.toLocaleString()} pcs</small></div><b className="is-pending">View materials</b></button>; })}</div>{!projectIds.length && <section className="terra-approval-detail terra-approval-empty"><h2>No proposals to review</h2><p>All proposals in this matching plan have already created delivery requests.</p></section>}</section>}{step === "materials" && <section className="terra-approval-workbench"><header><button type="button" className="terra-approval-back" onClick={() => setStep("projects")}>‹ Projects</button><p>{selectedProjectId}</p><h2>{selectedProjectId === "UNASSIGNED" ? "Unassigned project" : projectName(selectedProjectId)}</h2><span>Choose the material proposal to review.</span></header><div className="terra-approval-list" aria-label="Material proposals for selected project">{projectRequests.map((proposal) => { const itemOffer = terra.supply_offers.find((item) => item.id === proposal.supply_offer_id); return <button type="button" key={proposal.id} onClick={() => openReview(proposal.id)}><div><span>{proposal.id}</span><strong>{itemOffer ? materialName(itemOffer.material_id) : proposal.supply_offer_id}</strong><small>{proposal.proposed_quantity} {proposal.unit}</small></div><b className="is-pending">Review</b></button>; })}</div></section>}{step === "review" && selected && <section className="terra-approval-detail"><header><div><button type="button" className="terra-approval-back" onClick={() => setStep("materials")}>‹ Materials</button><p>Review proposal</p><h2>{offer ? materialName(offer.material_id) : selected.supply_offer_id}</h2><span>{offer && demand ? `${projectName(offer.source_project_id)} → ${projectName(demand.destination_project_id)}` : `${selected.supply_offer_id} → ${selected.demand_request_id}`}</span></div><StatusBadge status={selected.status} /></header><div className="terra-approval-facts"><article><span>Proposed release</span><b>{selected.proposed_quantity} {selected.unit}</b><small>Saved matching quantity</small></article><article><span>Currently reservable</span><b>{offer ? Math.max(0, (offer.confirmed_quantity ?? 0) - offer.reserved_active_quantity - offer.transferred_out_quantity) : "Checked later"} {offer?.unit ?? ""}</b><small>Rechecked at reservation</small></article><article><span>After approval</span><b>Requested</b><small>Still not reserved</small></article></div><section className="terra-approval-evidence"><div><p>Compatibility</p><h3>Backend-selected match</h3><ul><li>Eligible matching result</li><li>Proposed quantity and unit recorded</li><li>Stock is rechecked before reservation</li></ul></div><div><p>Operator review</p><h3>Confirm before request</h3><ul><li>Material condition</li><li>Source permission</li><li>Proposed quantity</li></ul></div></section><section className="terra-approval-decision"><div><p>Decision</p><h3>Ready for approval</h3><span>Approval atomically creates a requested delivery without reserving stock.</span></div><div className="terra-approval-actions"><button type="button" className="is-primary" disabled={busy} onClick={approve}>{busy ? "Approving…" : `Approve ${selected.proposed_quantity} ${selected.unit}`}</button></div></section></section>}</>}</section>;
}
