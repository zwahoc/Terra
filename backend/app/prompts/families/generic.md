# Document family: OTHER / uncertain / unknown
- Infer the document's real purpose from evidence, without force-fitting it into a familiar BOQ, PO or receipt category.
- Extract relevant identifiable material facts and source references. Treat unsupported lifecycle events as `record_kind=UNKNOWN`, not as automatically received stock or surplus.
- Use only allowed final document_type values; `OTHER` is appropriate when no supported top-level type fits.
- If the file actually combines several business document families, use `MIXED` and apply the relevant row semantics individually. Flag ambiguity instead of inventing certainty.
