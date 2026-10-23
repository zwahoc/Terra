# Document family: goods received note (GRN) / receiving acknowledgement
- Preserve GRN number, linked PO/DO, receiving project/store, receipt or acceptance date, item references, accepted quantity/unit, shortage/rejection notes, and relevant supporting approval evidence.
- A clear accepted quantity is `record_kind=RECEIPT`. Never substitute ordered/shipped quantity for accepted quantity where they differ.
- A GRN is evidence of a receipt event, not automatically the latest on-hand stock or surplus quantity. No GRN top-level FileDraft enum exists: use `document_type=OTHER`, unless genuinely mixed.
