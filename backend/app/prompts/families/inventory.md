# Document family: inventory / stocktake / stock balance
- Preserve each material's count/balance and its explicit basis: counted on-hand, system balance, available, reserved, in transit, damaged, lot/batch and stocktake/as-of date.
- `ON_HAND_INVENTORY` requires explicit stock-on-hand evidence. Keep reserved, issued, book balance and physical counts separate; never add snapshots, net movements or infer surplus by subtracting local needs.
- Use `CONFIRMED_SURPLUS` only if the document explicitly declares that status; even then it is merely an unapproved draft. The final document_type may be `INVENTORY`.
