# Stage: CROSS_CHECK_BATCH (tool-free)

Review successful and failed per-file provisional outcomes, compare their document IDs/revisions, named projects, item descriptions/specifications, quantities, dates and provenance, and return exactly one `BatchCrossCheck` JSON object under its supplied schema.

- Flag supported `POSSIBLE_DUPLICATE`, `POSSIBLE_REVISION`, `CONFLICT`, `SHARED_CONTEXT` and `MISSING_INFORMATION` findings. Reference **only** genuine current-run `submission_ids`, at least one per finding.
- Distinguish related PO, DO and GRN events from duplicate transactions. Their references may form one procurement chain, but are not additive physical stock contributions.
- Include important gaps due to failed or incompletely processed submissions. Preserve uncertainty where links or revisions are not proven.
- Group equivalent findings; explain evidence succinctly. Do not fabricate conflicts to populate the result.
- Do not call tools, resolve new IDs, change per-file outputs, create proposals, aggregate stock/demand/surplus, approve, publish or initiate matching.
- Return the required `summary` and supported `findings` as JSON only; use an empty findings list if nothing is supported.
