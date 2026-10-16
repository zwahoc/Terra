import { useState } from "react";
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
import { rememberActiveOptimisationRun, rememberedActiveOptimisationRun } from "../lib/optimisation-preview";
import "./top-navigation.css";
import "./semantic-colors.css";
import "./terra-app.css";

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
  const [page, setPage] = useState<AppPage>("overview");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeRunId, setActiveRunId] = useState(() => rememberedActiveOptimisationRun());
  const projectId = "ALL";

  const navigate = (nextPage: AppPage) => {
    setPage(nextPage);
  };

  const openPersistedPlan = (runId: string) => {
    rememberActiveOptimisationRun(runId);
    setActiveRunId(runId);
    navigate("approvals");
  };

  return (
    <div className={`terra-side-shell terra-top-shell ${drawerOpen ? "is-drawer-open" : ""}`}>
      <aside className="terra-side-navigation" onMouseEnter={() => setDrawerOpen(true)} onMouseLeave={() => setDrawerOpen(false)}>
        <button className="terra-side-brand" type="button" onClick={() => navigate("overview")} aria-label="Terra home"><img src="/terra-wordmark.png" alt="Terra" /></button>
        <nav aria-label="Terra workspace sections">
          {navigation.map((item) => { const Icon = item.icon; return <button className={`terra-side-link terra-side-link--${item.group} ${item.id === page ? "is-active" : ""}`} key={item.id} type="button" onClick={() => navigate(item.id)} data-label={item.label}><Icon aria-hidden="true" /><span>{item.label}</span></button>; })}
        </nav>
        <button className="terra-side-profile" type="button" aria-label="Open operator profile"><span>TO</span><b>Operator</b><small>Single-operator workspace</small></button>
      </aside>
      <div className="terra-side-content">
        <main>
            {page === "overview" && <OverviewPage projectId={projectId} navigate={navigate} />}
            {page === "materials" && <MaterialsPage />}
            {page === "matching" && <MatchingPage onPlanPersisted={openPersistedPlan} />}
            {page === "approvals" && <ApprovalsPage runId={activeRunId} />}
            {page === "transfers" && <TransfersPage projectId={projectId} />}
            {page === "upload" && <UploadPage />}
            {page === "impact" && <ImpactPage projectId={projectId} />}
        </main>
      </div>
    </div>
  );
}
