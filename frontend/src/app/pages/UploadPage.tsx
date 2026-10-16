import { useEffect, useState } from "react";
import StatusBadge from "../../components/StatusBadge";
import { FileUpload } from "@/components/ui/file-upload";
import { PageIntro } from "./page-primitives";
import "./upload-animation.css";
import "./upload-components.css";
import "./upload-file-upload.css";

type DraftMaterial = {
  id: number;
  name: string;
  quantity: string;
  unit: string;
  category: string;
  length: string;
  width: string;
  thickness: string;
  colour: string;
  finish: string;
  materialType: string;
  intendedUse: string;
  condition: string;
  availableFrom: string;
  massPerUnit: string;
  checked: boolean;
};
const blankMaterial = (id: number): DraftMaterial => ({
  id,
  name: "",
  quantity: "",
  unit: "pcs",
  category: "PAVING_BLOCK",
  length: "",
  width: "",
  thickness: "",
  colour: "",
  finish: "",
  materialType: "",
  intendedUse: "",
  condition: "",
  availableFrom: "",
  massPerUnit: "",
  checked: false,
});

function MaterialValidationCard({
  row,
  number,
  editing,
  onChange,
  onEdit,
  onSave,
  onDelete,
}: {
  row: DraftMaterial;
  number: number;
  editing: boolean;
  onChange: (
    field: Exclude<keyof DraftMaterial, "id" | "checked">,
    value: string,
  ) => void;
  onEdit: () => void;
  onSave: () => void;
  onDelete: () => void;
}) {
  const [selectedMatch, setSelectedMatch] = useState("");
  const ready = [
    row.name,
    row.quantity,
    row.unit,
    row.category,
    row.condition,
    row.availableFrom,
    row.length,
    row.width,
    row.thickness,
    row.colour,
    row.finish,
    row.materialType,
    row.intendedUse,
  ].every(Boolean);
  const matchState = selectedMatch
    ? "Matched"
    : row.name && row.quantity
      ? "Partly matched"
      : "Not matched";
  const field = (
    label: string,
    key: Exclude<keyof DraftMaterial, "id" | "checked">,
    type = "text",
    hint?: string,
  ) => (
    <label className="terra-field">
      <span>
        {label}
        {hint && <small>{hint}</small>}
      </span>
      <input
        type={type}
        value={row[key] as string}
        disabled={!editing}
        onChange={(event) => onChange(key, event.target.value)}
      />
    </label>
  );
  return (
    <article className={`terra-material-card ${editing ? "is-editing" : ""}`}>
      <header className="terra-material-card-head">
        <div>
          <span className="terra-material-number">
            Material {String(number).padStart(2, "0")}
          </span>
          <h3>{row.name || "Unnamed material"}</h3>
        </div>
        <div className="terra-card-actions">
          <StatusBadge status={row.checked ? "ACCEPTED" : "REVIEW_REQUIRED"} />
          {editing ? (
            <button
              type="button"
              className="terra-text-button"
              disabled={!ready}
              onClick={onSave}
            >
              Save
            </button>
          ) : (
            <button
              type="button"
              className="terra-icon-button"
              onClick={onEdit}
              aria-label={`Edit material ${number}`}
              title="Edit material"
            >
              ✎
            </button>
          )}
          <button
            type="button"
            className="terra-icon-button is-danger"
            onClick={onDelete}
            aria-label={`Remove material ${number}`}
            title="Remove material"
          >
            ×
          </button>
        </div>
      </header>
      <fieldset disabled={!editing} className="terra-material-fields">
        <div className="terra-material-grid primary">
          {field("Material name", "name")}
          {field("Quantity", "quantity", "number")}
          {field("Unit", "unit")}
          {field("Condition", "condition")}
          {field("Available from", "availableFrom", "date")}
          {field(
            "Mass per unit",
            "massPerUnit",
            "number",
            "optional · for carbon comparison",
          )}
        </div>
        <details className="terra-specifications" open={editing}>
          <summary>Specifications</summary>
          <div className="terra-material-grid specifications">
            {field("Category", "category")}
            {field("Length (mm)", "length", "number")}
            {field("Width (mm)", "width", "number")}
            {field("Thickness (mm)", "thickness", "number")}
            {field("Colour", "colour")}
            {field("Finish", "finish")}
            {field("Material type", "materialType")}
            {field("Intended use", "intendedUse")}
          </div>
        </details>
      </fieldset>
      <div className="terra-catalogue-match">
        <div>
          <span>Catalogue match</span>
          <strong
            className={`is-${matchState.toLowerCase().replace(" ", "-")}`}
          >
            {matchState}
          </strong>
        </div>
        <select
          value={selectedMatch}
          disabled={!editing}
          onChange={(event) => setSelectedMatch(event.target.value)}
          aria-label={`Choose a Terra material for material ${number}`}
        >
          <option value="">Choose a Terra material</option>
          <option value="existing">Use the closest catalogue material</option>
          <option value="new">Keep as a new material record</option>
        </select>
      </div>
    </article>
  );
}


export default function UploadPage() {
  const [fileName, setFileName] = useState<string | null>(null);
  const [documentState, setDocumentState] = useState<"idle" | "reading" | "ready">("idle");
  const [projectName, setProjectName] = useState("");
  const [projectCode, setProjectCode] = useState("");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [materialRows, setMaterialRows] = useState<DraftMaterial[]>([
    blankMaterial(1),
  ]);
  const [editingId, setEditingId] = useState<number | null>(1);
  const [lastDeleted, setLastDeleted] = useState<DraftMaterial | null>(null);
  useEffect(() => {
    if (documentState !== "reading") return;
    const timer = window.setTimeout(() => setDocumentState("ready"), 1150);
    return () => window.clearTimeout(timer);
  }, [documentState]);
  const reviewedCount = materialRows.filter((row) => row.checked).length;
  const updateRow = (
    id: number,
    field: Exclude<keyof DraftMaterial, "id" | "checked">,
    value: string,
  ) =>
    setMaterialRows((rows) =>
      rows.map((row) =>
        row.id === id ? { ...row, [field]: value, checked: false } : row,
      ),
    );
  const addRow = () => {
    const id = Date.now();
    setMaterialRows((rows) => [...rows, blankMaterial(id)]);
    setEditingId(id);
  };
  const removeRow = (id: number) => {
    const removed = materialRows.find((row) => row.id === id);
    if (
      !removed ||
      !window.confirm(
        `Delete ${removed.name || "this material"} from the draft?`,
      )
    )
      return;
    setLastDeleted(removed);
    setMaterialRows((rows) => rows.filter((row) => row.id !== id));
    if (editingId === id) setEditingId(null);
  };
  const undoDelete = () => {
    if (lastDeleted)
      setMaterialRows((rows) =>
        [...rows, lastDeleted].sort((a, b) => a.id - b.id),
      );
    setLastDeleted(null);
  };
  const registerReady =
    projectName.trim() &&
    projectCode.trim() &&
    location.trim() &&
    reviewedCount === materialRows.length &&
    materialRows.length > 0;
  return (
    <>
      <PageIntro label="Add a project" title="Create a project from a document">
        Upload the source file, then review each material before it becomes
        available for matching.
      </PageIntro>
      <section className="terra-upload-layout">
        <form
          className="terra-upload-card"
          onSubmit={(event) => event.preventDefault()}
        >
          <section className="terra-upload-source">
            <p className="terra-eyebrow">Project document</p>
            <label
              className={`terra-dropzone ${fileName ? "is-selected" : ""} is-${documentState}`}
            >
              <input
                type="file"
                accept=".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg"
                onChange={(event) => {
                  const nextFile = event.target.files?.[0]?.name ?? null;
                  setFileName(nextFile);
                  setDocumentState(nextFile ? "reading" : "idle");
                }}
              />
              <span className="terra-upload-icon">↑</span>
              {documentState === "reading" && <span className="terra-document-scan" aria-hidden="true"><i /><i /><i /></span>}
              <strong>{fileName ?? "Choose a document"}</strong>
              <small>
                {documentState === "reading"
                  ? "Reading material rows"
                  : fileName
                    ? "Ready for your review"
                    : "PDF, Excel, CSV, PNG or JPG"}
              </small>
              <span className="terra-file-button">
                {fileName ? "Choose another file" : "Choose file"}
              </span>
            </label>
            <div className="terra-aceternity-upload">
              <FileUpload
                onChange={(files) => {
                  const nextFile = files[0]?.name ?? null;
                  setFileName(nextFile);
                  setDocumentState(nextFile ? "reading" : "idle");
                }}
              />
            </div>
            {fileName && (
              <div className="terra-upload-progress" role="status">
                <span>
                  <i />
                  {documentState === "reading" ? "Preparing review" : "Document ready"}
                </span>
                <small>
                  {documentState === "reading" ? "Organising the draft material list…" : "Open the material cards below to check each detail."}
                </small>
              </div>
            )}
          </section>
          <section className="terra-project-panel">
            <div>
              <p className="terra-eyebrow">New project details</p>
              <h2>Where do these materials belong?</h2>
            </div>
            <div className="terra-project-fields">
              <label className="terra-field">
                <span>Project name</span>
                <input
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  placeholder="e.g. Elmina Phase F"
                />
              </label>
              <label className="terra-field">
                <span>Project code</span>
                <input
                  value={projectCode}
                  onChange={(event) => setProjectCode(event.target.value)}
                  placeholder="e.g. DEMO-06"
                />
              </label>
              <label className="terra-field">
                <span>Township / location</span>
                <input
                  value={location}
                  onChange={(event) => setLocation(event.target.value)}
                  placeholder="e.g. Elmina"
                />
              </label>
              <label className="terra-field">
                <span>Document type</span>
                <select defaultValue="Inventory list">
                  <option>Inventory list</option>
                  <option>Material schedule</option>
                  <option>Site survey</option>
                </select>
              </label>
            </div>
            <label className="terra-field">
              <span>
                Notes <small>optional</small>
              </span>
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Add context that will help with the review."
              />
            </label>
            <button
              className="terra-primary-button"
              type="submit"
              disabled={!registerReady}
            >
              Register project <span>→</span>
            </button>
          </section>
        </form>
        <section className="terra-manual-review">
          <header className="terra-review-header">
            <div>
              <p className="terra-eyebrow">Material validation</p>
              <h2>Review the material list</h2>
              <p>
                Open a material to correct it, then save it when you are
                satisfied.
              </p>
            </div>
            <span className="terra-review-count">
              {reviewedCount}/{materialRows.length} saved
            </span>
          </header>
          <div className="terra-manual-list">
            {materialRows.map((row, index) => (
              <MaterialValidationCard
                key={row.id}
                row={row}
                number={index + 1}
                editing={editingId === row.id}
                onChange={(field, value) => updateRow(row.id, field, value)}
                onEdit={() => setEditingId(row.id)}
                onSave={() => {
                  setMaterialRows((rows) =>
                    rows.map((item) =>
                      item.id === row.id ? { ...item, checked: true } : item,
                    ),
                  );
                  setEditingId(null);
                }}
                onDelete={() => removeRow(row.id)}
              />
            ))}
          </div>
          {lastDeleted && (
            <aside className="terra-undo">
              <span>Material removed.</span>
              <button type="button" onClick={undoDelete}>
                Undo
              </button>
            </aside>
          )}
          <button type="button" className="terra-add-row" onClick={addRow}>
            + Add another material
          </button>
        </section>
      </section>
    </>
  );
}
