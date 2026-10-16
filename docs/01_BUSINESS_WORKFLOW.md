# 01 — Terra business workflow and domain rules

**Runtime boundary:** All application actions enter through FastAPI from the React/TypeScript/Tailwind frontend. Framework-independent Python services perform the rules below; a repository/Python REST adapter persists through Firebase SQL Connect backed by PostgreSQL. Server authentication/connectivity and concurrent-write behavior still need validation. This document describes future behavior; it does not authorize application implementation. The separately authorized local seed milestone is documented in LOCAL_DEVELOPMENT.md.

## 1. Domain vocabulary: never merge these concepts

| Record type | Means | Eligible for reservation? |
|---|---|---|
| BOQ (bill of quantities) | Planned work/material quantities | No |
| Purchase order | Quantity ordered, not necessarily delivered | No |
| Inventory | Recorded on-hand material, may still be needed locally | No, not by itself |
| Potential surplus | Forecast release or calculated excess, not confirmed | No; suggestions only |
| Confirmed surplus offer | Quantity physically identified and declared releasable | Yes, subject to positive stock and compatibility |
| Demand request | Validated outstanding need by another project | Receives an allocation, not automatically a purchase |
| Allocation proposal | What algorithm recommends | No stock impact |
| Transfer | Approved/committed movement with quantities and status | May reserve/dispatch stock |
| Confirmed use | Actual reused quantity evidenced/recorded | Counts toward reuse metrics |

An LLM can classify/extract a BOQ or PO row and *suggest* its meaning; deterministic Python code calculates potential surplus and outstanding demand from documented stock, local needs, procurement/fulfilment and commitment inputs. Review determines whether it becomes a valid demand/supply record. A BOQ is **not** proof of outstanding demand without procurement/fulfilment context. The prototype's confirmations represent human checks, not engineering certification or proof of ownership.

## 2. Step-by-step end-to-end business workflow

**A. Existing data enters:** project A inventory or project B material requirement is recorded in the system. Document metadata and extract rows track origin; raw source files arrive later.

**B. AI extraction and review:** classify source type; parse raw descriptions, quantities/units/specifications; map to canonical catalogue. Pending/unverified rows remain drafts. A human-like demo review action may mark a row `ACCEPTED` or `CORRECTED`. Do not auto-confirm surplus based on AI confidence.

**C. Supply and demand verification:** the source confirms unused stock and permission for potential release; destination confirms outstanding requirement and need-by date. Offers might be potential, confirmed, suspended or closed. Only confirmed stock participates in reservation.

**D. Eligibility and optimisation:** validate source != destination, material dimensions/grade/finish/canonical units, timing, available quantities, reservations, incoming demand commitments, and any other required business restrictions. Construct proposals with explanations and reason codes. Multiple competing demands and supplies are supported.

**E. Environmental comparison:** for each *feasible* allocation, calculate hypothetical production emissions avoided and additional route/handling impacts. If factors are incomplete, report `INSUFFICIENT_DATA` and keep the operational match separately eligible. Prefer an environmental objective that makes assumptions transparent.

**F. Review and confirmation:** a single demo operator performs representative source/destination confirmation steps. Selected eligible proposal -> transfer request -> confirmations/approval -> reservation. Requests, selection and approval alone establish no stock hold; successful atomic reservation establishes the source hold and recipient incoming commitment together. No separate project-user identities are required.

**G. Dispatch and receipt:** upon dispatch, issue stock out of the source while adjusting active reservation exactly once. Record actual quantity dispatched/received. For the initial MVP API, dispatch and receipt are each one full-quantity operation; the receipt endpoint cannot record a partial or missing delivery. Existing discrepancies remain explicit and untouched pending a separately defined resolution workflow. Receipt is *not* equivalent to reuse.

**H. Actual reuse:** destination confirms how much was actually incorporated or otherwise reused. Count actual use only once; never claim the whole proposed or dispatched amount was reused.

**I. Environmental evidence and export:** create/recalculate a forecast assessment for proposals and a separate actual-use-based assessment for completed usage. Export project/source/receiver/material/units/quantity/time/factor assumptions/evidence/reuse and estimated avoided emissions. This is Pantas-*ready* only as a **proposed** exchange, not integrated with Pantas.

## 3. Worked allocation example (entirely synthetic)

- `PRJ-A` holds `SUP-A`: 1,000 **confirmed** grey concrete pavers, 200×100×60 mm, `pcs`, releasable 20 Oct 2026.
- `PRJ-B` needs 600 matching pavers by 25 Oct.
- `PRJ-C` needs 400 matching pavers by 29 Oct.
- **One possible proposal:** A→B 600, A→C 400. Other feasible suppliers/distances may produce a different environmental optimum.
- Merely generating those two proposals leaves available stock at 1,000.
- If A→B 600 is **reserved**, A's `reserved_active_quantity` becomes 600; available-for-new-reservation becomes 400.
- If 600 are **dispatched**, A's reservation decreases by 600 and `transferred_out_quantity` increases by 600. Available remains 400.
- If B **receives** 580 and **actually uses** 550, B's confirmed reused count is 550, not 600. Discrepancies must be recorded; B's open demand is still 50 at minimum unless the shortage is resolved another way. Do not implicitly return the 20 missing units to A's stock.
- If one unit is counted in actual reuse, never count it again from another stage, transfer-event row or alternative optimisation proposal.

## 4. Quantities and invariants

For each offer with confirmed quantity `Q`, active reserved `R`, dispatched/transferred-out `D`:

`reservable = max(0, Q - R - D)`

Require `Q >= 0`, `R >= 0`, `D >= 0`, `R + D <= Q`. The reference time is the snapshot time; future scheduled transfers are commitments, not physical dispatches.

For each demand with required quantity `N`, actual fulfilled `F`, active incoming commitments `C`:

`available_to_plan = max(0, N - F - C)`  
`remaining_unfulfilled = max(0, N - F)`.

`F` increases only upon valid confirmed use, not on mere receipt. Other procurement/fulfilment records are not modelled in the seed. `C` begins at successful reservation and includes unfulfilled promises through dispatch, receipt and partial use until used or explicitly resolved. Requested/approved transfers have no commitment yet. Count each transfer once, not once per status/event.

For example, 600 promised units with 550 used leave 50 unfulfilled. The unused/missing 50 remain committed until their disposition is explicitly resolved; a `REUSED` label alone must not make them available for a second allocation. The exact partial-transfer closure representation needs confirmation, recorded in Document 07. The seed must explain its discrepancy/resolution assumptions through notes and event payloads rather than fabricate a return or completion.

For a transfer: `0 <= actually_used_quantity <= received_quantity <= dispatched_quantity <= approved_quantity`. A transfer may be `RECEIVED` with used quantity zero. A partially reused transfer must expose the actual amount, not force `actually_used = received`.

A `CANCELLED` transfer releases **only still-active reservation**, not stock that was already dispatched. Returning goods after dispatch needs a separate documented reversal/return action; do not manufacture stock on cancellation.

All coupled changes (`transfers`, `supply_offers`, `demand_requests`, `transfer_events`) happen atomically and are idempotent by command/event ID. Individual status updates cannot leap over prerequisites.

## 5. Allowed example transition path

`PROPOSAL -> (operator approval) -> REQUESTED -> RESERVED -> IN_TRANSIT -> RECEIVED -> REUSED`.

Approving a proposal creates the `REQUESTED` transfer with demo confirmations, without real authenticated identities. The operator may cancel a request before dispatch with recorded reason; once dispatched, cancellation/restock must not silently roll back physical movement. Keep append-only event timestamps logically ordered. `APPROVED` remains only for historical seed compatibility, not the new transition path. Dispatch, receipt and use remain required stages in the API and seed histories.

## 6. Compatibility rules for three starter categories

- Same canonical material ID is ideal; explicit alternative catalogue equivalences may be supported but only after required properties agree.
- **Paver:** type/material, length, width, thickness, colour/finish if critical.
- **Brick:** type (clay/concrete), dimensions, stated grade/strength if applicable; missing technical suitability means `REVIEW_REQUIRED`, not automatic equivalence.
- **Tile:** ceramic/porcelain/type, dimensions, thickness if specified, finish, slip-rating/grade if critical; different floor/wall intended use may block match.
- Unit normalization: `PCS`, `pieces`, `units` may convert to canonical `pcs` where semantics are unambiguous; `m²` to `pcs` requires explicit tile face dimensions **and** defensible coverage/wastage assumptions; no silent conversion.
- Condition `UNUSED` and traceability are initial reuse eligibility requirements. `RECOVERED`, `UNKNOWN`, damaged or missing-condition supply should be held for review.
- Availability date must be no later than demand deadline, with transport/handling lead time if modelled. Flag borderline cases.
- Never propose a source and receiving project be the same, unless modelling local reuse separately (not MVP).

## 7. Carbon and ESG arithmetic example

**ALL numbers below are fictional demonstration assumptions.** For 600 blocks, 2.5 kg/block, 0.75 kgCO2e/block assumed new-production factor, 25 km additional transfer, 0.12 kgCO2e/(tonne·km) assumed transport factor:

- Hypothetical avoided new production = `600 pcs * 0.75 kgCO2e/pcs = 450 kgCO2e`.
- Freight mass = `600 * 2.5 / 1000 = 1.5 tonnes`.
- Additional transport = `1.5 tonnes * 25 km * 0.12 kgCO2e/(tonne·km) = 4.5 kgCO2e`.
- If additional handling is **unknown**, `net_avoided_kgco2e = null`, NOT `445.5`; status `INSUFFICIENT_DATA`.
- If an **explicit synthetic assumption** says handling = `10 kgCO2e`, simplified net = `450 - 4.5 - 10 = 435.5 kgCO2e`.

Real comparisons must define both baseline and reuse scenarios consistently (including baseline transport/disposal if within scope), functional equivalence, material provenance, lifecycle boundary and appropriate emission factor source and geography. Proposed savings and post-confirmation savings must never be summed as two separate results.

After partial reuse, avoided production uses only confirmed used quantity. Transport/handling must account for the movement actually performed, including discrepancies according to an explicit assessment boundary. Do not silently scale all trip emissions down to used quantity. The policy for allocating these costs remains open in Document 07; an undefined boundary means an incomplete net estimate.

**ESG metrics:** separately report `proposed_reuse_mass_t`, `confirmed_reuse_mass_t`, `possibly_prevented_waste_t` only when supported by baseline evidence, and `estimated_net_avoided_tco2e`. Avoided emissions must not be subtracted from official Scope 1/2/3 inventory automatically. An internal material transfer is not inherently waste-diversion reporting and does not generate a carbon credit.
