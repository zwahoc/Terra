# Shared construction-material business semantics

Use these evidence distinctions independent of the routing family:

- **BOQ / measured work / BOM / MTO / design requirement**: describes planned scope or material requirements. Never infer purchase, receipt, on-hand stock, outstanding balance or surplus from it.
- **Purchase order**: ordered or committed supply. Not proof of delivery, acceptance, ownership transfer or stock.
- **Delivery order / despatch note**: items listed for dispatch/delivery; dispatch is not acceptance. Use `record_kind=UNKNOWN` for a dispatch-only row because no dispatch enum exists, retaining item details as evidence.
- **Goods received note / signed receipt**: explicit received/accepted quantities may justify `RECEIPT` only to the degree indicated by actual acknowledgements. Do not inflate accepted quantity from ordered quantity.
- **Inventory / stocktake**: stock at a stated location/time. Separate book balance, count, reservation, movements and outstanding local requirement. Do not calculate stock balances.
- **Remaining local need / demand**: identify only explicitly documented need basis. Never calculate outstanding demand from BOQ, order or delivery by subtraction.
- **Potential surplus / declared confirmed surplus**: only an explicit source surplus statement or status supports the corresponding draft kind. Either remains provisional pending human confirmation; a pre-demolition salvage estimate is not already available stock.
- **Transfers / issues / returns**: distinguish requested, approved, issued, dispatched, received and actually used. No direct TRANSFER/ISSUE enum exists, so preserve unsupported stages with UNKNOWN, raw fields and a short issue rather than inventing an operational event.
- **Technical certificates / compliance evidence**: describe material specifications and documented findings; never certify compatibility or imply quantities are physically present.

Keep document links (PO/DO/GRN/revision/item numbers) in existing structured/source fields where supported. Financial totals and rate columns are not material amounts.
