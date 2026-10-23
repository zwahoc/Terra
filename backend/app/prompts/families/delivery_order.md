# Document family: delivery order / dispatch note
- Preserve DO number, any linked PO, dispatch date, consignor, destination, item references, shipped quantity/unit and material or batch specifications.
- Distinguish **shipped / intended-to-deliver** from **received / accepted**. A standard unsigned delivery order alone is NOT a receipt. In this case use `record_kind=UNKNOWN` and retain shipment evidence in raw_fields/issues, rather than fabricating a receipt enum.
- If the same document explicitly acknowledges accepted goods with signed receiving evidence and quantity, a separate, clearly evidenced `RECEIPT` interpretation may be appropriate; do not assume all shipped quantities were accepted.
- No `DELIVERY_ORDER` top-level FileDraft enum exists: use `document_type=OTHER` unless the file is genuinely MIXED.
