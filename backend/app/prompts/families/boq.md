# Document family: BOQ / bill of quantities
- A BOQ measures proposed work and/or material requirements. It is not proof of purchase, physical stock, excess material or available supply.
- Inspect every described numbered schedule item; account for each in source_items. Extract only useful physical-material candidates, preserving source item/page and raw work or material quantities separately. Several materials may share a source item.
- Labour-only, preliminaries, service and financial lines belong in internal CONTEXT coverage, not material records. Mixed work/material lines can reveal grounded material candidates; work quantity does not automatically measure each material. Mark inference and retain unknown component quantities.
- Preserve measured-work units (`m2`, `m3`, `m`, `item`, `LS`, etc.) exactly; they do not necessarily represent purchasable units. Do not convert work quantities into kg/pieces without source evidence.
- Ignore tender rates, amounts, subtotals and page summary totals as material quantities. Totals do not replace underlying item rows.
- For BOQ rows, prefer `record_kind=PLANNED_REQUIREMENT` and `document_type=BOQ` where the document genuinely is a BOQ. Retain unknown dates as null.
