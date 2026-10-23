# 05 — AI ingestion, review and publication contract

This is the consolidated approved ingestion contract. It describes current requirements and implemented boundaries, not a phased execution plan. The [SRS](TERRA_SRS_v1.0.md) defines product requirements; [Document 09](09_ARCHITECTURE_UPDATE.md) governs architecture; [Document 08](08_MODULE_INTERFACES.md) indexes implemented HTTP interfaces.

## Responsibility and authority

Python orchestrates document preparation, AI interpretation, material/project resolution, deterministic stock/need previews, human review and atomic publication. Matching follows committed relevant changes; ingestion never alters transfers to resolve a correction.

AI understands useful project/material facts, retrieves Terra context and proposes identities/treatments. It does not approve records, compute authoritative stock, certify suitability, register emission-factor datasets, operate transfers or execute arbitrary SQL/web requests. Raw document instructions are untrusted content.

## Intake and supported evidence

- Upload all related files and deliberately start analysis. A file may contain several projects; multiple files may describe one project. A selected project is a hint, not a forced association.
- Original bytes, filenames, hashes and available page/paragraph/cell/item references remain intact. View source opens the whole document; excerpts/highlights are not required.
- Standalone manual submissions and linked replacements are operator-provided without documentary provenance. They require their own review/approval; no dummy document is created.
- PDF preparation extracts available text and renders numbered page images for DeepSeek. Gemini retains its native PDF path. Scanned content uses model interpretation, not claimed local OCR.
- Decoded PNG/JPEG/TIFF/GIF/WebP frames, DOCX, XLSX/XLSM, UTF-8 text and CSV/TSV have implemented preparation paths. Office readers inspect text/tables and embedded images with supplied locators. Formula cells lacking cached values remain uncertain. Legacy DOC/XLS and unsupported objects require conversion or manual attention.
- Large documents use progressive disk preparation, reusable provider image references and connected page groups where actual constraints require them. One file remains one review unit. Never silently omit pages/rows to fit a request or claim support for every extension.

File identity and semantic identity differ. Identical bytes reuse compatible saved extraction by default; explicit reanalysis retains earlier attempts. Renamed copies share the same hash. Different scans/revisions need semantic comparison and operator-reviewed treatment, not automatic duplication or replacement.

## Processing sequence

```text
save sources/context → tool-free classification → validated trusted prompt routing
    → fresh extraction conversation with Terra tools
    → save validated extraction → separate same-model reconciliation
    → separate batch cross-check → prepared human review
    → file approval → separate complete-batch publication
```

Each selected/comparison model has an isolated proposal namespace and original result. A complete successful model may be explicitly selected as primary; ordinary analysis uses that exact model and never silently falls back. Comparison remains deliberate. Extraction, reconciliation and batch checking show saved progressive results independently; a later failure does not discard compatible completed work.

Active trusted modules are `backend/app/prompts/`. Classification selects only permitted backend modules, never a document-supplied filename. Core, extraction, semantics, family, runtime and page-group rules compose the extraction prompt. Reconciliation, batch checking and narrow repair have their own conversations/instructions. Prompt/content/configuration identities participate in reuse decisions.

## Terra tool context and identity resolution

`analysis_tools.py::tool_definitions` exposes typed project search/context, project proposal, material search/details/proposal, document search and existing-record reads, plus `search_materials_bulk`. Read tools return Terra records; creation tools create run-local proposals only. Existing IDs and draft IDs are distinct. A proposal from another model run cannot be treated as published.

DeepSeek chooses alternative search terms and ANY/ALL matching over names, references/codes and specifications, including bulk requests. Terra returns complete requested matches through stable pagination, without relevance ranking or top-N suppression. The model follows non-null cursors and decides whether identities/specifications are equivalent. An empty exact phrase search is not evidence that no equivalent exists. New categories and attributes are open-ended; relevant physical differences become distinct identities.

Read snapshots describe observed contents, not a complete physical ledger or an isolated transaction. Missing collections/quantities are not proof of zero. Fresh context and publication guards remain necessary.

## Extract useful facts without turning every row into inventory

Main output contains supported project identity/location/organisation/dates and physical-material information. Non-material services/preliminaries remain internal source coverage. Complete item inspection does not require a material record for every numbered source row.

A work item may imply one or more grounded materials. Preserve inference explanation/fields and source work quantities; do not copy a measured-work quantity into every implied ingredient. Unknown material quantities remain null. Do not invent specifications, packaging, stock, release, ownership or timing.

The schema in `backend/app/schemas/analysis.py` defines FileDraft and its nested contracts. It retains document_type/summary, project_refs/project_info, records, assumptions/issues, page_coverage and source_items. Records preserve raw fields, identity references, specifications, quantity meaning/basis, exact quantity/unit, timing, source locators/item/page links and treatment/predecessors. Model/source output remains separate from later review edits.

## Validation, repair and execution limits

Programmatic schema/reference/quantity/unit/date/provenance checks run after model output. PDF page acknowledgements and recognised numbered-item coverage must be complete; Office locators must correspond to supplied evidence. Text and images of the same source are not separate physical contributions. Coverage proves inspection/accounting, not semantic correctness.

Safe formatting recovery handles supported JSON wrappers/numeric presentation and identical repeated members while retaining original output. Conflicting duplicate keys, nonfinite values, ambiguous quantities, truncation and unsupported inference are not silently guessed. General prompt self-validation checks interpretation against the full schema, not one special enum case.

Narrow model repair exposes only implicated permitted paths, revalidates the complete candidate and rejects unrelated value/identity/raw-source/locator changes. Source-item reference repair may correct the exact implicated row reference and coverage membership. No-progress/invalid repairs retain the candidate and history for inspection/retry; they do not publish partial output.

There is no total tool-call/step spending cutoff. Equivalent first requests execute, second requests can reuse observed evidence, and a third identical operation is blocked locally rather than failing the entire file. No-progress loops receive a finalisation opportunity. Real provider/request/context/decoder/time/resource limits still apply and are reported explicitly.

DeepSeek requests HIGH reasoning throughout and the configured provider-maximum output allowance. Gemini has its separate configured allowance/pacing. Provider/transport/quota failures are retained and require explicit retry; no automatic model substitution or repeated uncertain paid request. Usage tracking has no application spending hard stop; configured/free-tier estimates are not provider invoices or billing activation.

## Reconciliation and failures

Reconciliation compares the saved extraction with fresh same-project/material/document/observation context. It proposes new information, newer observations, possible duplicate/revision, conflict or uncertainty. It does not rewrite extraction, create new identity proposals or calculate authoritative stock balances.

Files can be retried individually, explicitly skipped or linked to manual replacement. Successful files cannot publish while failures remain pending. Added files in an unpublished batch require deliberate analysis and a new cross-check. Same-model review update preserves operator edits and invalidates only affected dependent approvals. Restored context requires fresh comparison/acknowledgement; changed prompt/input/context may invalidate checkpoint reuse. Published batches are immutable; corrections use later evidence.

## Prepared review and human decisions

Supported recommendations live in a provisional overlay, never an inferred human decision. The operator reads each file, edits disagreements, resolves real ambiguities and approves it once. That approval accepts displayed identities, values, treatments, supported conversions and applicable stock/release acknowledgements. It does not bypass blockers, stale context or missing evidence. Legacy working reviews require an explicit upgrade; they are not silently overwritten.

Preparation can use exact verified reconciliation predecessors, unambiguous new-information ADD, quantity-free technical HISTORY_ONLY, retained gross/net columns, a stated receiving window and a uniquely documented product-specific conversion. It does not infer conversions from another product, copy conflicting physical specifications or turn possible overlap into definite replacement. Explicit project master updates are distinct from association edits; conflicting/null/blank corrections cannot erase stored facts.

Operators can directly override quantities/interpretation or exclude a row without writing a reason. Audit records edited-by-operator and preserves the original. Example: “100 bags delivered to Projects A and B” may mean100 total or100 each. AI flags the ambiguity and proposes editable project-specific values; no forced sum is imposed without confirmation.

Short editors lead with material identity, quantity meaning/value, relevant dates and evidence treatment. Open-ended specification rows and retained fields remain available. Exact conversion previews and readable predecessor choices are read-only assistance, not approval. Saved forms use their opening revision and retain unsaved edits on failure/navigation cancellation.

## Quantity treatment and previews

| Treatment | Effect |
|---|---|
| ADD | A separate included contribution, subject to duplicate/overlap review |
| REPLACE | Supersede exact eligible observations of the same project/material/meaning/comparable unit; retain history |
| HISTORY_ONLY | Retain evidence with no active quantity effect |
| EXCLUDED | Resolve the value while omitting it from publication |

Project/document observations remain separate from catalogue identity and released offers. Current heads/effective observations are counted once; superseded/history-only records do not increase stock. Conversions preserve source quantity/unit, target unit, factor and factual basis. Python performs exact multiplication; no silent rounding or unsupported packaging conversion.

Calculations refresh automatically after review edits, without another model call. A complete, non-overlapping stock scope must be acknowledged for stock-based results. Potential excess uses available stock minus local requirement; net uncovered demand uses explicit net demand minus active incoming commitments when declared. Otherwise sufficiently validated local requirement/stock inputs can support a computed gap. Procurement observations are not automatic received stock or mapped commitments.

Confirmed release is a subset of stock, checked against available stock and remaining local need. A calculated excess alone grants no release authority. Missing local requirements or other inputs do not block unrelated valid facts; unavailable balances remain undetermined. Direct operator release/demand declarations remain separately identifiable and validated.

## Approval and publication

A file may contain multiple projects. All its included values must be valid/resolved; an excluded value counts as resolved. Manual submissions have separate approval. File approval checks revision, source/review/context dependency digests and deterministic preview. Related identity/context changes can invalidate dependent approvals.

Publication validates every included approval/resolution, current database state, exact quantities, identity resolution, predecessor targets, stock/commitments and required timing. One named guarded transaction applies the entire batch, new confirmed identities, immutable contributions, supersession/scope changes, supported offers/demands, explicit project corrections, audit, replay-safe receipt and durable matching intent. Any failed guard rolls back the complete change set. A saved commit is not repeated because background matching failed.

Corrections affecting transfer-linked stock cannot alter reserved/in-transit material. The operator resolves the transfer through its own workflow or excludes the correction. Ingestion never cancels, releases or restocks it. Cancel/release/reapprove is pre-dispatch only; post-dispatch exception handling is outside this version.

The worker processes matching-relevant commits across all projects for affected materials. History-only changes need no matching work. Superseded recommendations become unusable; reservation/transfer history remains valid evidence. Publication does not reserve, dispatch, receive or record use.

## Presentation and known limits

Review shows project facts, unresolved questions, material values and relevant file consequences before historical analysis details. Technical schedules may use compact tables. Generated IDs/original diagnostics remain in details; saved notes are labelled as historical rather than rewritten as current facts. Exact-item navigation connects publication→Matching→confirmation→Deliveries→Report. Sidebar entry starts fresh; explicit resume/back preserves saved work.

Known review limitations remain visible: a model can omit a needed-from date even when a receiving window is stated, or create a quantity-free shared technical record without project association. Current validation still requires project resolution for an included technical record. Such blockers require operator resolution/exclusion; no automatic waiver or claim of perfect model interpretation is made.

Carbon-factor datasets are reference setup, not automatically created by ingestion. Material weight/route/master facts use separate explicit confirmation. Preserve demonstrative factor disclosures and never imply a source document alone produced a verified carbon result.

## Scope exclusions

No compulsory chatbot, external product lookup, override explanations, source-excerpt generation, price tracking, monetary savings, single-project-file restriction, arbitrary material-family whitelist, full movement ledger, expanded condition/damage management, partial batch publication, automatic confidence approval or account system is introduced. Actual provider/model/format semantic accuracy, very large datasets, broad exception/native accessibility and cloud acceptance remain separately testable limits.
