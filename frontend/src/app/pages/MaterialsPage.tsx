import { useState } from "react";
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import StatusBadge from "../../components/StatusBadge";
import { supplyViews, terra } from "../../data/terra";
import { EmptyState, PageIntro } from "./page-primitives";
import "./inventory.css";
import "./materials-redesign.css";
import "./inventory-status-fix.css";

export default function MaterialsPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [availability, setAvailability] = useState<"all" | "ready" | "review">("all");
  const [inventoryPage, setInventoryPage] = useState(1);
  const [pageSize, setPageSize] = useState(5);
  const materialFor = (id: string) => terra.materials.find((item) => item.id === id);
  const rows = supplyViews.map((offer) => ({ ...offer, material: materialFor(offer.material_id) }));
  const categories = [...new Set(rows.map((row) => row.material?.category ?? "OTHER"))].sort();
  const shownRows = rows.filter((row) => {
    const text = `${row.material_name} ${row.id} ${row.project_name} ${row.material?.reference_code ?? ""}`.toLowerCase();
    return text.includes(query.trim().toLowerCase()) &&
      (category === "all" || row.material?.category === category) &&
      (availability === "all" || (availability === "ready" ? row.reservable_quantity > 0 : row.reservable_quantity === 0));
  });
  const overview = [
    { name: "Ready", value: rows.filter((row) => row.reservable_quantity > 0).length, fill: "#5c9a69" },
    { name: "Held", value: rows.filter((row) => row.reserved_active_quantity > 0).length, fill: "#c4a456" },
    { name: "Review", value: rows.filter((row) => row.surplus_status !== "CONFIRMED").length, fill: "#8a9f98" },
  ];
  const materialMix = categories.map((name) => ({ name: name.replaceAll("_", " "), value: rows.filter((row) => row.material?.category === name).length }));
  const pageCount = Math.max(1, Math.ceil(shownRows.length / pageSize));
  const currentPage = Math.min(inventoryPage, pageCount);
  const paginatedRows = shownRows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const ready = overview[0].value;
  const held = overview[1].value;
  const review = overview[2].value;

  return (
    <>
      <PageIntro label="INVENTORY" title="Material supply">
        Available, held, and review-required supply.
      </PageIntro>
      <section className="terra-inventory-summary" aria-label="Inventory supply overview">
        <article><span>Material lines</span><b>{rows.length}</b><small>Registered supply records</small></article>
        <article className="is-ready"><span>Ready to share</span><b>{ready}</b><small>Confirmed and reservable</small></article>
        <article className="is-held"><span>Currently held</span><b>{held}</b><small>Has an active reservation</small></article>
        <article><span>Needs review</span><b>{review}</b><small>Not ready for matching</small></article>
      </section>
      <section className="terra-inventory-charts">
        <article>
          <header><div><p>SUPPLY STATUS</p><h2>What can move next?</h2></div><span>Material lines</span></header>
          <ResponsiveContainer width="100%" height={210}><BarChart data={overview} margin={{ top: 12, right: 4, left: -24, bottom: 0 }}><XAxis dataKey="name" tickLine={false} axisLine={false} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} /><Tooltip cursor={{ fill: "#edf2e9" }} /><Bar dataKey="value" radius={[5, 5, 0, 0]}>{overview.map((item) => <Cell key={item.name} fill={item.fill} />)}</Bar></BarChart></ResponsiveContainer>
        </article>
        <article>
          <header><div><p>SUPPLY MIX</p><h2>Material categories</h2></div><span>All supply</span></header>
          <div className="terra-inventory-donut"><ResponsiveContainer width="100%" height={210}><PieChart><Pie data={materialMix} dataKey="value" nameKey="name" innerRadius={51} outerRadius={78} paddingAngle={3}>{materialMix.map((item, index) => <Cell key={item.name} fill={["#5c9a69", "#c4a456", "#698a9b", "#a47b86", "#7d9875"][index % 5]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer><ul>{materialMix.map((item) => <li key={item.name}><span>{item.name}</span><b>{item.value}</b></li>)}</ul></div>
        </article>
      </section>
      <section className="terra-inventory-table-section">
        <header><button type="button" className="terra-primary">+ Add material</button></header>
        <div className="terra-inventory-filters" aria-label="Inventory filters">
          <label>Search inventory<input value={query} onChange={(event) => { setQuery(event.target.value); setInventoryPage(1); }} placeholder="Search material name, ID or project" /></label>
          <label>Category<select value={category} onChange={(event) => { setCategory(event.target.value); setInventoryPage(1); }}><option value="all">All categories</option>{categories.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label>
          <label>Availability<select value={availability} onChange={(event) => { setAvailability(event.target.value as "all" | "ready" | "review"); setInventoryPage(1); }}><option value="all">All supply</option><option value="ready">Ready to share</option><option value="review">Needs review</option></select></label>
        </div>
        <div className="terra-inventory-table-wrap">
          <div className="terra-inventory-table-scroll">
          <table className="terra-inventory-table"><thead><tr><th>Material</th><th>Supply ID</th><th>Project</th><th>Category</th><th>Listed</th><th>Held</th><th>Ready now</th><th>Status</th></tr></thead><tbody>{paginatedRows.map((row) => <tr key={row.id}><td><b title={row.material_name}>{row.material_name}</b><small>{row.material?.reference_code ?? row.material_id}</small></td><td>{row.id}</td><td>{row.project_name}</td><td><span className="terra-category-chip">{(row.material?.category ?? "Other").replaceAll("_", " ")}</span></td><td>{row.declared_quantity} {row.unit}</td><td>{row.reserved_active_quantity} {row.unit}</td><td className={row.reservable_quantity > 0 ? "is-ready" : ""}>{row.reservable_quantity} {row.unit}</td><td><StatusBadge status={row.surplus_status} displayLabel={row.surplus_status} /></td></tr>)}</tbody></table>
          {!shownRows.length && <EmptyState>No inventory lines match these filters.</EmptyState>}
          </div>
          <footer className="terra-inventory-pagination" aria-label="Inventory pages"><div className="terra-pagination-actions"><button type="button" disabled={currentPage === 1} onClick={() => setInventoryPage(currentPage - 1)}>← Previous</button><span>Page {currentPage} of {pageCount}</span><button type="button" disabled={currentPage === pageCount} onClick={() => setInventoryPage(currentPage + 1)}>Next →</button></div><i aria-hidden="true" /><label>Rows per page <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setInventoryPage(1); }}><option value="5">5</option><option value="10">10</option><option value="20">20</option></select></label></footer>
        </div>
      </section>
    </>
  );
}

