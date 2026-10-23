# Document family: supplier invoice / financial claim
- Retain item descriptions, quantities/units and references as supporting transaction evidence where directly stated, but an invoice is proof of billing, not independent receipt or stock.
- Do not use prices, taxes, rates, discounts or line monetary totals as physical quantities. Do not calculate costs or savings.
- If no supported material lifecycle state is actually demonstrated, use `record_kind=UNKNOWN` and `document_type=OTHER` rather than treating billed quantity as RECEIPT.
