# Terra baseline scenario index

All records are synthetic, snapshot 2026-10-12. IDs refer to `terra_seed.json` in this directory. Plans are designed fixtures, not outputs from an implemented optimiser. No LLM, raw file or real site inspection was used.

| Spec scenario / requested scenario | Records | Expected demonstration |
|---|---|---|
| S01 / A exact match | PRJ-001, PRJ-002, MAT-001, SUP-001, DEM-001, ALC-001 | Same grey 200×100×60 mm paver; historical source snapshot permits 600 pcs. Current source stock is depleted. |
| S02 / B different descriptions | ROW-001, ROW-023, MAT-001 | Two reviewed descriptions share one catalogue ID. |
| S03 / C specification mismatch | MAT-015, MAT-016, SUP-008, DEM-007, ALC-012 | Same-sized ceramic tile has different thickness, finish and floor/wall use; ineligible. |
| Partial allocation / D | SUP-003, DEM-003, ALC-003, TRF-003 | 300 of 500 needed is reserved, leaving 200 newly allocatable. |
| S04 / E one supply, two demands | SUP-001, DEM-001, DEM-002, ALC-001, ALC-002, TRF-006, TRF-007 | One 1,000-pcs source supplied 600 and 400; never 1,100. |
| S05 / H carbon-aware suppliers | SUP-001, SUP-002, DEM-001, ALC-001, ALC-009, IMP-001, IMP-002, RTE-001, RTE-006 | 25 km vs 6 km, synthetic symmetric routes. Compare per-piece emissions because allocation quantities differ. |
| S06 / F potential surplus | SUP-007, ROW-007 | Declared 300, confirmed null, no holds or dispatched stock, zero reservable. |
| S07 / G date mismatch | SUP-009, DEM-008, ALC-013 | Release 25 October exceeds 18 October deadline; rejected. |
| S08 current partial reservation | SUP-003, TRF-003 | Confirmed 800 minus reserved 300 leaves 500 source units; recipient has 200 uncommitted units. |
| S09 / J partial physical use | ALC-001, TRF-006, DEM-001, IMP-005 | Proposed/approved/dispatched 600, received 580, used 550. Remaining 50 are unresolved incoming commitments. Full-trip freight is recorded; handling boundary and net remain incomplete. |
| S10 / I lifecycle stages | TRF-001, TRF-002, TRF-003, TRF-004, TRF-005, TRF-006, TRF-007, TRF-008 | Requested, approved, reserved, in transit, received, two reused records and pre-dispatch cancellation. Complete ordered histories in transfer_events. |
| S11 rejected/expired proposals | ALC-012, ALC-013, ALC-014 | Zero physical commitments. Expired brick forecast remains an operationally compatible historical candidate. |
| S12 / L missing carbon data | MAT-011, SUP-010, DEM-009, ALC-014, IMP-004 | No mass or production factor; net null, INSUFFICIENT_DATA. |
| S13 BOQ/PO/inventory boundary | DOC-003, DOC-006, ROW-045, ROW-046, ROW-047 | Planned 2,000 and ordered 1,800 remain extraction records; pending 500 on-hand does not publish surplus. |
| S14 fulfilled/cancelled demand | DEM-002, DEM-013, TRF-007 | Fulfilled demand has 400 actually used; cancelled demand has no new availability or incoming commitment. |
| S15 competing strategies | RUN-001, RUN-002, ALC-001, ALC-009, ALC-010, ALC-011 | Same hashed pre-transfer snapshot, different objectives. Alternative recommendations never count as execution. |
| K historical dashboard | TRF-006, TRF-007, IMP-005, IMP-006 | 950 pcs actual use, 2.375 t known reused mass, 3 distinct participating source/recipient projects. One complete actual net estimate of 291.04 kgCO2e, with the partial-use assessment reported separately as incomplete. |
| Correction and review | ROW-048, ROW-049, ROW-050 | Original `12O` corrected to 120 with review details; rejected and pending rows retained. |

The 31 transfer events exceed the suggested 15–25 range because eight distinct stages include two six-event reuse histories. The spec explicitly gives complete histories priority. No events are fabricated merely to meet a quota.

`REUSED` here records positive confirmed use, including partial use; TRF-006 is not declared closed. Its 50-unit incoming promise remains until an explicit later disposition policy exists. No missing/damaged unit is returned to source stock. This fixture preserves the open business decision in Document 07.
