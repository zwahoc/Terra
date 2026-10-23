# 01 — Business workflow and quantity rules

## Material information has distinct meanings

| Information | Meaning | Reservable? |
|---|---|---|
| BOQ/planned requirement | Work or material planned for a project | No |
| Purchase order | Committed procurement, not receipt | No |
| Receipt | Evidence of delivery/acceptance in its source scope | Not by itself |
| On-hand inventory | Observed physical stock that may still be needed locally | Not by itself |
| Remaining local requirement | Material still required for unfinished local work before applying stock | No |
| Outstanding demand | Uncovered need already net of applicable local stock/fulfilment | Recipient of an allocation |
| Potential surplus | Possible excess, not an authorised release | No |
| Confirmed surplus | Identified unused material authorised for release | Subject to all eligibility guards |
| Allocation proposal | A recommended source/recipient quantity | No stock effect |
| Transfer | A separately confirmed movement with reservation and physical stages | Holds stock after reservation |
| Actual use | Material confirmed used by the recipient | Counts as reuse once |

## End-to-end process

1. Upload related files blindly or with an optional project hint. Start analysis explicitly; upload alone does not approve or publish anything.
2. AI classifies/interprets documents with controlled Terra lookups and provisional project/material proposals. Saved extraction is reconciled against fresh stored records, followed by a batch cross-check.
3. The operator reviews projects, material identities, quantities, meanings, treatments, conversions and timing. They edit disagreements, answer real questions or exclude values without a mandatory written reason.
4. Supported recommendations may be prepared for reading. One explicit file approval accepts its displayed values/identities/conversions and applicable stock/release acknowledgements. Every included file or manual submission needs approval.
5. Failed files must succeed on retry, be explicitly skipped or be replaced by reviewed manual information. Only the complete resolved/approved batch publishes, atomically and replay-safely.
6. Matching-relevant commits trigger automatic three-method matching across affected materials and all their projects. Draft edits and previews do not trigger matching. A matching failure does not undo publication.
7. The operator chooses an alternative, reviews an individual transfer and explicitly confirms suitability and quantity. One transaction confirms and reserves source stock and recipient capacity together.
8. Dispatch the full reserved quantity, confirm full receipt separately, then record positive actual-use increments up to the received remainder.
9. Saved use and applicable confirmed input corrections trigger automatic immutable actual-impact revisions. Current reporting excludes stale estimates while an update is pending or failed.

## Quantity invariants

For a confirmed released offer with quantity Q, active reservation R and cumulative dispatched amount D:

```text
available_to_reserve = max(0, Q - R - D)
0 <= R + D <= Q
```

For recipient required quantity N, actually fulfilled F and active incoming commitments C:

```text
newly_allocatable_need = max(0, N - F - C)
remaining_unfulfilled = max(0, N - F)
0 <= F + C <= N
```

Incoming commitments begin at reservation and persist through dispatch/receipt until use or valid pre-dispatch cancellation. A used status alone does not release unused received material. Never sum alternative recommendations as simultaneous commitments.

```text
0 <= actually_used <= received <= dispatched <= approved <= proposed
reserved + dispatched <= approved
```

Surplus is a subset of stock. A stock count of150 with100 released remains150 physical pieces, not 250. An explicit net gap is not reduced by local stock a second time. Missing remaining need is unknown, not zero.

## Additions, corrections and evidence

Each published contribution retains project, material, source and meaning. Different specifications and incomparable units stay separate.

- ADD records separate information/contributions.
- REPLACE supersedes exact eligible earlier observations, preserving original evidence and history.
- HISTORY_ONLY retains evidence with no active quantity effect.
- EXCLUDED resolves a value without publishing it.

A newer count of 120 after 100 may mean a corrected120 or separate stock totalling 220; it is not automatically a new delivery. AI recommends a treatment, and the operator approves it. Stock-based calculations require a confirmed complete, non-overlapping input scope. Corrections to transfer-linked stock are blocked for transfer resolution; ingestion never cancels or restocks a transfer.

## Transfer lifecycle

The normal journey is:

```text
current proposal → explicit confirmation + atomic reservation → RESERVED
    → full dispatch → IN_TRANSIT
    → full receipt → RECEIVED
    → positive actual-use increment → REUSED
```

REQUESTED/APPROVED remain for historical compatibility; approved-but-unreserved is not a normal new-plan stage. The operator confirms each transfer individually, not an entire plan atomically.

A proposed quantity can be reduced before confirmation subject to fresh checks/forecast. Changing a reserved quantity requires cancellation, release and a fresh confirmation. No in-place reservation amendment or post-dispatch cancellation is allowed. Partial shipments, shortages, returns, damage and discard resolution are not implemented in this version; never mark a short receipt as full.

For 600 received and 550 used, 50 remain allocated to the recipient. Later use can consume that remainder. Receipt alone contributes no actual reuse. Cancellation before dispatch releases both holds exactly once; dispatched goods cannot be silently restored to source.

## Compatibility and timing

Use the same specific reviewed catalogue identity and consistent material snapshots. Known specification conflicts, different material IDs and unconfirmed suitability remain guarded. Categories are open-ended; no preset family whitelist or implicit engineering certification applies. Explicit extra specification requirements remain possible.

Units must match or have an explicitly confirmed product-specific conversion. Dimensions, unit mass and pieces-per-area ratios are not interchangeable. Preserve original source quantities and the confirmed conversion basis; no silent rounding.

Future opportunities remain visible, but confirmation must satisfy current timing. Earliest dispatch/reservation is the maximum of planning date, source availability and recipient needed-from date. Same-township planning uses one day lead time; different townships use two. This is an internal documented assumption, not verified haulage duration. Arrival must meet the deadline and dispatch the source availability window.

## Carbon and reporting

Production avoidance uses confirmed used quantity. Transport and combined loading/unloading use the full moved quantity, including during partial use. Missing factor, weight, route or required boundary leaves the relevant component/net unknown. No zero substitution or unsupported distance/weight is invented.

Forecast, chosen-quantity confirmation forecast and actual-use results have separate provenance. Preserve immutable revisions and select one current assessment per scope; never add forecast and actual as achieved benefit. See [Impact API](IMPACT_API.md) for factor applicability and equations.
