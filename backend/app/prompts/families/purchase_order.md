# Document family: purchase order (PO)
- Extract PO number/revision, ordering and supplying organisations if stated, receiving project, item/product references, descriptions/specifications, quantity and unit, and document/delivery dates with their exact meanings.
- Treat ordered lines as `PURCHASE_ORDER`, not `RECEIPT`, `ON_HAND_INVENTORY` or surplus. Do not infer partial receipt or remaining quantity from other documents without explicit evidence and authorised calculation.
- Preserve amended, cancelled or replacement PO indicators and links to any earlier PO. Only suggest `REPLACE`/`HISTORY_ONLY` when grounded in actual stored context; never apply one.
- A supplier's quoted price or purchase total is not a material quantity. Final document_type: `PURCHASE_ORDER`.
