# Document family: material requirements / BOM / MTO / material schedule
- Identify whether quantities are design take-off, scheduled procurement, reserved for use or simply theoretical bill-of-materials quantities. Preserve that basis in available raw fields or issues.
- Keep individual components/materials and technical attributes (dimensions, grade, location, construction phase) distinct. A design-derived quantity is not an actual stock balance.
- Map unambiguously stated planned needs to `PLANNED_REQUIREMENT`. Use `OUTSTANDING_DEMAND` or `REMAINING_LOCAL_REQUIREMENT` **only** where the source explicitly states that meaning.
- The final `FileDraft.document_type` has no BOM/MTO enum: use `OTHER`, or `DEMAND` only if the document is explicitly a demand/request rather than merely a design/material list.
