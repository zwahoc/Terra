# Document family: material issue / return / adjustment
- Identify request, actual issue, material consumption, return to store, write-off, adjustment and supporting voucher stage separately.
- Preserve movement direction, quantity, unit, site/store, dates, voucher references and item/source provenance. Do not treat an issue/return as a current-stock quantity or calculate a new balance.
- When a movement does not directly correspond to a supported `record_kind`, use `UNKNOWN` with source evidence, not a made-up movement enum. Use `OTHER` top-level unless the file is genuinely inventory/mixed.
