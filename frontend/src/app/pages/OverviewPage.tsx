import { useState } from "react";
import { IconArrowUpRight, IconChevronRight } from "@tabler/icons-react";
import type { AppPage } from "../page-types";
import { candidateMatches, dashboard, demandViews, supplyViews, terra, transferStages, transferViews } from "@/data/terra";
import "./overview-dashboard.css";

type OverviewProps = { projectId: string; navigate: (page: AppPage) => void };

const stageLabel = (value: string) => value.replaceAll("_", " ").toLowerCase();

export default function OverviewPage({ projectId, navigate }: OverviewProps) {
  const [expandedTransfer, setExpandedTransfer] = useState(transferViews[0]?.id ?? "");
  const visibleSupply = supplyViews.filter((item) => projectId === "ALL" || item.source_project_id === projectId);
  const visibleDemand = demandViews.filter((item) => projectId === "ALL" || item.destination_project_id === projectId);
  const confirmedSupply = visibleSupply.filter((item) => item.surplus_status === "CONFIRMED" && item.reservable_quantity > 0);
  const activeTransfers = transferViews.filter((item) => ["RESERVED", "IN_TRANSIT", "RECEIVED"].includes(item.status));
  const eligibleMatches = candidateMatches.filter((item) => item.compatibility_result === "ELIGIBLE");
  const readyToReserve = confirmedSupply.reduce((total, item) => total + item.reservable_quantity, 0);
  const openDemand = visibleDemand.filter((item) => item.request_status === "OPEN").reduce((total, item) => total + item.remaining_unfulfilled_quantity, 0);

  return <div className="overview-dashboard">
    <header className="overview-dashboard__header">
      <div><h1>Material operations.</h1><p>Confirmed stock, proposed matches, and hand-offs that need an operator decision.</p></div>
      <div className="overview-dashboard__header-actions"><span>As of {terra.metadata.as_of_date}</span><button type="button" onClick={() => navigate("matching")}>Review matches <IconArrowUpRight aria-hidden="true" /></button></div>
    </header>

    <section className="overview-kpis" aria-label="Operational summary" data-ui>
      <article><span>Confirmed stock</span><strong>{readyToReserve.toLocaleString()} <small>pcs</small></strong><p>available to reserve</p></article>
      <article><span>Proposed matches</span><strong>{eligibleMatches.length}</strong><p>ready for review</p></article>
      <article><span>Open demand</span><strong>{openDemand.toLocaleString()} <small>pcs</small></strong><p>awaiting a source</p></article>
      <article><span>Live transfers</span><strong>{activeTransfers.length}</strong><p>reserved, moving, or received</p></article>
    </section>

    <section className="overview-workspace">
      <section className="overview-priority" data-ui>
        <header className="overview-section-heading"><div><h2>Next decisions</h2><p>Eligible paths are proposed only. Review before stock is reserved.</p></div><button type="button" onClick={() => navigate("approvals")}>Approvals <IconChevronRight aria-hidden="true" /></button></header>
        <div className="overview-decision-list">
          {eligibleMatches.slice(0, 3).map((match) => <button className="overview-decision-row" key={match.id} type="button" onClick={() => navigate("matching")}><span className="overview-decision-material"><b>{match.material_name}</b><small>{match.source_project_name} → {match.destination_project_name}</small></span><span className="overview-decision-quantity"><b>{match.maximum_preview_quantity.toLocaleString()} {match.unit}</b><small>proposed quantity</small></span><IconChevronRight aria-hidden="true" /></button>)}
        </div>
      </section>

      <section className="overview-stock">
        <header className="overview-section-heading"><div><h2>Confirmed stock</h2><p>Unused supply that can be reserved now.</p></div><button type="button" onClick={() => navigate("materials")}>Inventory <IconArrowUpRight aria-hidden="true" /></button></header>
        <div className="overview-material-strip" aria-label="Reusable construction materials"><img src="/terra-material-board.png" alt="Concrete block texture" /><img src="/terra-material-board.png" alt="Ceramic tile texture" /><img src="/terra-material-board.png" alt="Reclaimed material texture" /><img src="/terra-material-board.png" alt="Material review surface" /></div>
        <div className="overview-stock-list">
          {confirmedSupply.slice(0, 4).map((offer) => <div className="overview-stock-row" key={offer.id}><div><b>{offer.material_name}</b><span>{offer.project_name} · available {offer.available_from}</span></div><strong>{offer.reservable_quantity.toLocaleString()} <small>pcs</small></strong></div>)}
        </div>
      </section>
    </section>

    <section className="overview-transfers" data-ui>
      <header className="overview-section-heading"><div><h2>Active hand-offs</h2><p>Reservation, dispatch, receipt, and actual use remain separate workflow stages.</p></div><button type="button" onClick={() => navigate("transfers")}>Deliveries <IconArrowUpRight aria-hidden="true" /></button></header>
      <div className="overview-transfer-list">
        {activeTransfers.map((transfer) => {
          const isExpanded = transfer.id === expandedTransfer;
          const currentStage = transferStages.indexOf(transfer.status as typeof transferStages[number]);
          return <article className={isExpanded ? "overview-transfer is-expanded" : "overview-transfer"} key={transfer.id}><button type="button" onClick={() => setExpandedTransfer(isExpanded ? "" : transfer.id)} aria-expanded={isExpanded}><span className="overview-transfer-id">{transfer.id}</span><span className="overview-transfer-material">{transfer.material_name}</span><span className="overview-transfer-route">{transfer.source_project_name} → {transfer.destination_project_name}</span><span className={`overview-transfer-status overview-transfer-status--${transfer.status.toLowerCase()}`}>{stageLabel(transfer.status)}</span><IconChevronRight aria-hidden="true" /></button>{isExpanded && <div className="overview-transfer-detail"><div>{transferStages.map((stage, index) => <span className={index <= currentStage ? "is-complete" : ""} key={stage}>{stageLabel(stage)}</span>)}</div><p><b>{transfer.approved_quantity} pcs requested</b> · {transfer.reserved_quantity} reserved · {transfer.dispatched_quantity} dispatched · {transfer.received_quantity} received · {transfer.actually_used_quantity} actually used</p></div>}</article>;
        })}
      </div>
    </section>

    <footer className="overview-reporting" data-ui><div><span>Confirmed actual use</span><strong>{dashboard.actual_reuse_tonnes.toFixed(3)} t</strong></div><p>Reported emissions are synthetic comparative estimates, not official inventory reductions, waste-diversion totals, or carbon credits.</p><button type="button" onClick={() => navigate("impact")}>Reporting basis <IconChevronRight aria-hidden="true" /></button></footer>
  </div>;
}
