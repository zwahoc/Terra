# Document family: inter-project transfer / stock transfer / POD
- Preserve originating and destination projects **per relevant row**, transfer/order numbers, material/specifications, quantity, dates and stage (requested, authorised, issued, dispatched, received, actually used).
- Don't treat a transfer request/dispatch as confirmed receipt or completed reuse. A receiver-signed accepted quantity may support `RECEIPT` as evidence, without mutating transfer state.
- Where both projects appear, add both resolved projects in project_refs, but assign each row's `project_ref` only with a clear and documented role; use null and issues for ambiguous associations.
- There is no transfer enum in `record_kind` or top-level `document_type`; use supported `RECEIPT` only for actual receipt, otherwise `UNKNOWN` and top-level `OTHER` or `MIXED`.
