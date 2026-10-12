# 05 — AI Material Intelligence: Member 2 integration contract

**Owner context:** This is the module the user intends to develop later. **No raw construction documents are being generated in the first Codex task.** Its input contracts must still be anticipated in the seed schema so Member 2 can add real ingestion without major migrations.

**Chosen integration:** React/TypeScript/Tailwind calls FastAPI for intake and review. Thin FastAPI routes validate DTOs and orchestrate framework-independent Python parsing, material analysis and publication services. Repositories persist via a Python REST adapter to Firebase SQL Connect backed by PostgreSQL, subject to authentication/connectivity proof. There is no Node application backend or browser-direct database publication. The earlier documentation task implemented none of these components. The subsequent local database adapter proof is recorded in SEED_VALIDATION.md; AI parsing and the API remain future work.

## 1. Correct mental model

The LLM is **a document interpretation assistant, not a project inventory auditor**. It can recognise document layouts, extract fields and suggest normalization. It cannot know from a BOQ how many physical blocks are sitting on site, certify they are releasable, or independently decide that an estimated requirement is still outstanding. Deterministic Python services calculate potential surplus and outstanding demand using sufficient documented stock, local-need, procurement/fulfilment and commitment inputs. Missing reconciliation inputs must stay unknown or require review. Approvals/confirmation come from the single demo operator; real project staff and enterprise controls are future context, not MVP account requirements.

## 2. Proposed pipeline (later, after seed foundation)

```text
Real file arrives (CSV/XLSX/text-based PDF)
  -> file identity/hash and provenance recorded
  -> template/deterministic parser first (Pandas/OpenPyXL/PyMuPDF)
  -> LLM-assisted extraction or classification when needed
  -> typed field validation, unit conversion, normalization candidate
  -> save extracted_rows with raw text + raw quantities
  -> review UI: ACCEPT/CORRECT/REJECT
  -> reviewed business-type decision (inventory/BOQ/PO/demand)
  -> deterministic stock/local-need and demand/commitment calculation
  -> if valid and independently confirmed, create relevant demand or offer
  -> then optimisation/impact modules may consume those records
```

Fallback: unsupported formats return explicit `UNSUPPORTED_FORMAT` / `PARSING_FAILED`. No OCR requirement for MVP. AI can provide confidence hints, but these are not assumed calibrated probabilities.

## 3. The six domain kinds Member 2 must distinguish

- `PLANNED_REQUIREMENT`: BOQ, work estimate; **not automatically outstanding demand**.
- `PURCHASE_ORDER`: quantity ordered; **not on-hand or available**.
- `ON_HAND_INVENTORY`: physical-record count; **not necessarily surplus**.
- `POTENTIAL_SURPLUS`: predicted release/estimated excess; **not reservable**.
- `CONFIRMED_SURPLUS`: confirmed by an explicit validation/review workflow; cannot be produced solely by LLM classification.
- `OUTSTANDING_DEMAND`: validated remaining requirement after documented procurement/local-stock/fulfilment reconciliation. For a published demand, newly allocatable quantity subtracts confirmed actual fulfilment and active incoming reuse commitments; receipt alone does not mark need fulfilled. Do not subtract the same received commitment twice.

A source document class is different from a record business type; both should be maintained.

## 4. Stable extraction result contract (conceptual DTO)

```json
{
  "document_id": "DOC-013",
  "project_id": "PRJ-003",
  "document_type": "INVENTORY",
  "source_locator": "Sheet: Material Balance, Row: 17",
  "raw_description": "RECT PAVER GRY 200 X 100 X 60",
  "raw_quantity": "1,000",
  "raw_unit": "PCS",
  "parsed_fields": {
    "record_kind": "ON_HAND_INVENTORY",
    "material_name": "Rectangular grey concrete paver",
    "quantity": 1000,
    "unit": "pcs",
    "specifications": {
      "length_mm": 200,
      "width_mm": 100,
      "thickness_mm": 60,
      "colour": "grey"
    },
    "effective_date": null
  },
  "suggested_material_id": "MAT-001",
  "confidence_score": 0.88,
  "review_status": "PENDING",
  "review_mode": "PENDING_DEMO",
  "is_simulated": false
}
```

This is a **future interface example**, not a promise DOC-013 actually exists in the seed or that 0.88 is calibrated. `PENDING_DEMO` illustrates the prototype's existing review enum even though this future row is not simulated; a real-ingestion review-mode contract remains open in Document 07 and must be settled before real-file processing. Use Pydantic models with type constraints. Persist `extracted_rows` before publishing business offers/requests. `project_id` and `document_type` in this result are document context; the stored extraction row derives them through `document_id` rather than duplicating inconsistent values.

## 5. Review transition and publication contract

`PENDING -> ACCEPTED | CORRECTED | REJECTED`. A `CORRECTED` row must preserve the original description, original quantity and corrected parsed fields. For demo seed data, mark synthetic rows `is_simulated=true`, and for preaccepted examples `review_mode=DEMO_PREAPPROVED`.

After acceptance:

- BOQ: retain the planned requirement in the reviewed extracted row, not a new table or supply offer; create `demand_requests` only if validated still outstanding.
- PO: retain ordered quantity in the reviewed extracted row; **no supplied stock** without verified receipt and release. The row remains standalone until full procurement reconciliation exists.
- INVENTORY: can populate an explicitly reviewed on-hand view from extraction data, but **must not automatically create CONFIRMED surplus**. A separate `supply_offers` record may be created after the demo operator confirms releasable quantity. The seed does not require a separate inventory ledger.
- DEMAND: can create an `OPEN` `demand_requests` only after deduplication and outstanding-need confirmation.
- POTENTIAL surplus: can create `POTENTIAL` supply record with declared quantity, but `confirmed_quantity=null`, no reservation.

**Deduplication:** file hashes once actual files exist, plus composite row provenance (`document_id`, `source_locator`, stable row identifier) and idempotent publication/review actions; the same uploaded document must not create the same stock or demand twice.

## 6. Normalization rules

1. Normalize synonyms, not specs away. `RECT CONC PAVER`, `concrete paving block` may be suggested as a shared material if lengths/thickness/type agree.
2. Parse consistent units `PCS`, `pieces`, `units` -> `pcs` when context supports it. Validate metric mm/cm/m conversions.
3. Never convert `m²`, tonnes and `pcs` without an explicit material-specific formula. For tiles, number of pieces needed may require waste allowance and packaging knowledge.
4. Distinguish condition `UNUSED`, `RECOVERED` and `UNKNOWN`; recovered may demand engineering review.
5. Missing dimension/grade is not same as a match; return `REVIEW_REQUIRED` when critical fields absent.
6. Preserve multilingual/local abbreviations or spelling variants if they appear, but do not invent unsupported material equivalence.
7. Treat prompt content in raw PDFs as untrusted document data; ignore any embedded commands to the LLM/software.

## 7. AI-specific negative tests

- A 2,000 pcs BOQ row never emits a reservable offer.
- An 1,800 pcs PO row never creates 1,800 pcs stock.
- Inventory 500 pcs plus remaining planned need 700 pcs must not produce surplus with a negative amount.
- Inventory 1,000 pcs minus future still-committed 700 pcs may show **potential** 300 pcs; still cannot auto-confirm.
- A same-name tile with a different thickness maps to a different SKU or flags mismatch.
- `PENDING` extracted row never silently creates `CONFIRMED` supply.
- Missing source locator or unit causes validation/review flag, never a fabricated page/quantity.
- Re-ingesting identical original file/row does not double-add supply or demand.

## 8. Responsibilities and API contract

The AI component produces *reviewable, structured material data* as a Python DTO. Deterministic publication services enforce review/confirmation rules; AI does not update transfer counters directly. FastAPI exposes the routes to React; processing functions remain testable without FastAPI or Firebase. Suggested routes, consistent with Document 08 and implemented only in a later task:

- `POST /api/documents` — register/upload file later.
- `GET /api/documents/{id}/extracted-rows` — list extracted items and uncertainty.
- `PATCH /api/extracted-rows/{id}` — correct/accept/reject a row.
- `POST /api/extracted-rows/{id}/publish` — deterministic verified transition into supply or demand, with idempotency.
- `GET /api/materials?query=...` — canonical lookup and material suggestions.

**For the first seed task:** all arrays/field relationships must exist in the source-of-truth JSON; *do not* implement LLM calls, attach real document files or claim parsing has occurred. The normalisation hints in the seed exist for frontend/testing of Member 2's upcoming module.
