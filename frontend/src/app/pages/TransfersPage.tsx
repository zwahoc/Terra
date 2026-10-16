import { useEffect, useMemo, useState } from "react";
import StatusBadge, { statusLabel } from "../../components/StatusBadge";
import { materialName, projectName, terra, transferStages } from "../../data/terra";
import { advanceTransfer, calculateActualImpact, listTransfers, type Transfer } from "../../lib/terra-api";
import { EmptyState, PageIntro } from "./page-primitives";
import "./deliveries-redesign.css";
import "./workflow-listing.css";

type DeliveryStep = "projects" | "deliveries" | "details";
const deliveryStatuses: Transfer["status"][] = ["REQUESTED", "RESERVED", "IN_TRANSIT", "RECEIVED", "REUSED"];
const actions: Partial<Record<Transfer["status"], "reserve" | "dispatch" | "receive" | "confirm-use">> = {
  REQUESTED: "reserve", RESERVED: "dispatch", IN_TRANSIT: "receive", RECEIVED: "confirm-use",
};

function Rail({ status }: { status: Transfer["status"] }) {
  const current = transferStages.indexOf(status);
  return <div className="terra-rail" aria-label={`Delivery stage: ${statusLabel(status)}`}>
    {transferStages.map((stage, index) => <span className={index < current ? "is-complete" : index === current ? "is-current" : ""} key={stage}><i>{index < current ? "✓" : index + 1}</i><small>{statusLabel(stage)}</small></span>)}
  </div>;
}

export default function TransfersPage({ projectId }: { projectId: string }) {
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [step, setStep] = useState<DeliveryStep>("projects");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [used, setUsed] = useState("");

  const load = () => {
    setState("loading");
    listTransfers().then((rows) => { setTransfers(rows); setState("ready"); }).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : "Transfer data is unavailable."); setState("error");
    });
  };
  useEffect(load, []);

  const deliveryTransfers = useMemo(() => transfers.filter((transfer) => {
    if (!deliveryStatuses.includes(transfer.status) || (transfer.status === "REQUESTED" && transfer.approved_quantity <= 0)) return false;
    const proposal = terra.allocation_proposals.find((item) => item.id === transfer.proposal_id);
    const offer = proposal && terra.supply_offers.find((item) => item.id === proposal.supply_offer_id);
    const demand = proposal && terra.demand_requests.find((item) => item.id === proposal.demand_request_id);
    return projectId === "ALL" || offer?.source_project_id === projectId || demand?.destination_project_id === projectId;
  }), [transfers, projectId]);
  const projectFor = (transfer: Transfer) => {
    const proposal = terra.allocation_proposals.find((item) => item.id === transfer.proposal_id);
    const demand = proposal && terra.demand_requests.find((item) => item.id === proposal.demand_request_id);
    return demand?.destination_project_id ?? "UNASSIGNED";
  };
  const projectIds = useMemo(() => [...new Set(deliveryTransfers.map(projectFor))].sort(), [deliveryTransfers]);
  const projectTransfers = useMemo(() => deliveryTransfers.filter((transfer) => projectFor(transfer) === selectedProjectId), [deliveryTransfers, selectedProjectId]);
  const selected = projectTransfers.find((transfer) => transfer.id === selectedId);
  const proposal = selected && terra.allocation_proposals.find((item) => item.id === selected.proposal_id);
  const offer = proposal && terra.supply_offers.find((item) => item.id === proposal.supply_offer_id);
  const demand = proposal && terra.demand_requests.find((item) => item.id === proposal.demand_request_id);
  const action = selected && actions[selected.status];
  const maxUse = Math.max(0, (selected?.received_quantity ?? 0) - (selected?.actually_used_quantity ?? 0));

  const openProject = (id: string) => { setSelectedProjectId(id); setSelectedId(""); setStep("deliveries"); };
  const openDelivery = (id: string) => { setSelectedId(id); setUsed(""); setStep("details"); };
  const run = async () => {
    if (!selected || !action) return;
    setBusy(true); setMessage("");
    try { await advanceTransfer(selected, action, action === "confirm-use" ? Number(used || maxUse) : undefined); load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Terra could not complete this action."); setState("ready"); }
    finally { setBusy(false); }
  };

  return <>
    <PageIntro label="DELIVERIES" title="Track each approved material hand-off">Choose a receiving project, then open one approved delivery to follow its hand-off.</PageIntro>
    {message && <p className="terra-workflow-message" role="status">{message}</p>}
    {state === "loading" && <EmptyState>Loading deliveries from Terra.</EmptyState>}
    {state === "error" && <EmptyState>{message}</EmptyState>}
    {state === "ready" && <section className="terra-delivery-workflow">
      {step === "projects" && <section className="terra-delivery-workbench"><header><h2>Choose a receiving project</h2><span>Only projects with approved materials ready for delivery are listed.</span></header><div className="terra-delivery-project-list">{projectIds.map((id) => { const projectDeliveries = deliveryTransfers.filter((transfer) => projectFor(transfer) === id); const count = projectDeliveries.length; const approvedQuantity = projectDeliveries.reduce((total, transfer) => total + transfer.approved_quantity, 0); return <button type="button" key={id} onClick={() => openProject(id)}><div><span>{id}</span><strong>{id === "UNASSIGNED" ? "Unassigned project" : projectName(id)}</strong><small>{count} approved delivery {count === 1 ? "record" : "records"} · {approvedQuantity.toLocaleString()} pcs</small></div><b>View deliveries</b></button>; })}</div>{!projectIds.length && <EmptyState>No approved materials are ready for delivery.</EmptyState>}</section>}
      {step === "deliveries" && <section className="terra-delivery-workbench"><header><button type="button" className="terra-delivery-back" onClick={() => setStep("projects")}>‹ Projects</button><p>{selectedProjectId}</p><h2>{selectedProjectId === "UNASSIGNED" ? "Unassigned project" : projectName(selectedProjectId)}</h2><span>Choose a delivery to view its current hand-off stage.</span></header><div className="terra-delivery-list">{projectTransfers.map((transfer) => { const itemProposal = terra.allocation_proposals.find((item) => item.id === transfer.proposal_id); const itemOffer = itemProposal && terra.supply_offers.find((item) => item.id === itemProposal.supply_offer_id); return <button type="button" key={transfer.id} onClick={() => openDelivery(transfer.id)}><span>{transfer.id}</span><strong>{itemOffer ? materialName(itemOffer.material_id) : "Transfer material"}</strong><small>{statusLabel(transfer.status)} · {transfer.approved_quantity.toLocaleString()} pcs</small><b>View details</b></button>; })}</div>{!projectTransfers.length && <EmptyState>No approved materials are ready for this project.</EmptyState>}</section>}
      {step === "details" && selected && proposal && offer && demand && <article className="terra-transfer terra-delivery-detail"><header><button type="button" className="terra-delivery-back" onClick={() => setStep("deliveries")}>‹ Deliveries</button><div className="terra-row"><div><p>{selected.id} · {proposal.id}</p><h3>{materialName(offer.material_id)}</h3><small>{projectName(offer.source_project_id)} → {projectName(demand.destination_project_id)}</small></div><StatusBadge status={selected.status} /></div></header><Rail status={selected.status} /><div className="terra-quantities"><span>Requested<b>{selected.approved_quantity}</b></span><span>Held<b>{selected.reserved_quantity}</b></span><span>Sent<b>{selected.dispatched_quantity}</b></span><span>Delivered<b>{selected.received_quantity}</b></span><span>Used<b>{selected.actually_used_quantity}</b></span></div><footer className="terra-transfer-actions">{action === "confirm-use" ? <label>Quantity confirmed used<input type="number" min="1" max={maxUse} value={used || String(maxUse)} onChange={(event) => setUsed(event.target.value)} /></label> : <small>{action ? "Ready for the next delivery action." : selected.status === "REUSED" ? "Actual use is confirmed." : "No further action is available."}</small>}{action ? <button type="button" disabled={busy} onClick={run}>{busy ? "Saving…" : action === "reserve" ? "Reserve requested quantity" : action === "dispatch" ? "Mark as dispatched" : action === "receive" ? "Confirm receipt" : "Confirm actual use"}</button> : selected.status === "REUSED" ? <button type="button" disabled={busy} onClick={async () => { setBusy(true); try { await calculateActualImpact(selected.id); setMessage("Actual-use impact calculated. Open Impact to review it."); } catch (error) { setMessage(error instanceof Error ? error.message : "Impact could not be calculated."); } finally { setBusy(false); } }}>Calculate actual impact</button> : null}</footer></article>}
    </section>}
  </>;
}
