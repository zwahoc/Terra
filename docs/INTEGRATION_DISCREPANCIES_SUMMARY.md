# Terra integration issues — simple team summary

Prepared: 16 October 2026, Asia/Kuala_Lumpur.

This summary describes the current Member 3/Member 4 integration. It records
open decisions; it does not approve or implement changes to existing rules.
The shared carbon calculation and non-persisting preview connection work, but
the following mismatches still need resolution.

## 1. A valid delivery plan can be blocked by reservation rules

Member 3 treats a demand's `needed_from` as the earliest permitted receipt date.
Member 4 currently also uses that date as the earliest permitted reservation date.

Example:

| Event | Date |
|---|---|
| Recipient can receive materials | 20 October |
| Transport takes | 2 days |
| Allocator plans dispatch | 18 October |
| Reservation needed | On or before dispatch |
| Current reservation rule permits reservation | From 20 October |

The allocator can recommend arrival on 20 October, but reservation on 18 October
is rejected. If the receipt deadline is also 20 October, waiting until then to
reserve prevents timely delivery under the same transport assumption.

**Decision needed:** distinguish reservation, dispatch and receipt dates. Agree
whether reservation may happen before the recipient's receipt window when the
source is currently reservable and a feasible delivery exists.

**Implementation implications:** any agreed change must update both Python
validation and the atomic SQL Connect checks, their generator and relevant tests.
Keep stock, recipient commitment, confirmation and suitability protections.

See the [detailed reservation timing issue](MEMBER_3_4_CARBON_COOPERATION.md#unresolved-integration-issue-reservation-timing).

## 2. Preview and saved carbon results can use different inputs

The calculation formula is shared, but the information supplied to it can differ.

| Preview | Saved proposal assessment |
|---|---|
| Uses the planning date for factor applicability | Uses the proposal creation date |
| Uses a detached snapshot of calculation inputs | Reads current database records |

Example: a preview is calculated on 16 October. The proposal is saved on
17 October after a factor or material weight changes. The saved forecast could
differ from the carbon result used to select the plan, even with the same formula.

**Decision needed:** preserve the agreed forecast inputs and activity date when
saving. A later recalculation using updated information should be explicitly
identified as a new revision, with its provenance retained.

This is separate from reservation timing: it concerns reproducible carbon
calculations, not whether the transfer can be scheduled.

See the [preview and saved assessment contracts](IMPACT_API.md).

## 3. Partial use has no agreed handling-cost rule

Example: 600 pieces are transported, but only 550 are used.

| Component | Current treatment |
|---|---|
| Avoided production | Based on 550 actually used pieces |
| Additional freight | Based on all 600 dispatched pieces |
| Processing/handling | Unknown while the partial-use boundary is unresolved |
| Net avoided carbon | Unknown because processing is unknown |
| Remaining 50 pieces | Stay committed pending explicit disposition |

The system preserves known components and returns missing values rather than
inventing an allocation or silently releasing the remaining material.

**Decisions needed:** agree the processing/handling boundary and, separately,
how unused material is retained, returned or released. Returning material must
not erase the freight emissions already incurred.

See the [impact calculation guide](IMPACT_API.md) and
[transfer workflow guide](TRANSFER_WORKFLOW_API.md).

## Unfinished connections — not conflicting rules

These are implementation tasks that remain after the relevant policies are agreed:

1. Run MAX_REUSE and MAX_NET_CO2E_AVOIDED against one shared frozen snapshot.
   The plans are alternatives; their quantities and emissions are not added together.
2. Save dictionary-shaped optimisation runs, allocation proposals and linked
   carbon assessments with IDs, timestamps, snapshots and provenance.
3. Create supporting impact revision heads for new proposals/transfers and
   commitment balances for new demands as part of their creation workflows.
4. Select proposals and create requested transfers for Member 4's existing
   approval and reservation workflow. Proposals alone never reserve stock.
5. Connect Member 1's comparison UI, including missing-carbon and stale-plan states.
6. Verify the complete flow with the emulator, including retries, stale inputs,
   atomic stock/demand checks and residual commitments.

## Recommended order

1. Agree reservation timing and forecast input/date consistency.
2. Build paired comparison using the existing non-persisting preview services.
3. Implement saving and selection/transfer creation with safe retry behaviour.
4. Connect the UI and verify the full emulator workflow.
5. Address partial-use handling and disposition before claiming complete carbon
   results for those cases; keep current incomplete flags until then.

## One-minute explanation for the team

- **Timing:** we can recommend a delivery that the reservation rules currently block.
- **Carbon consistency:** preview and saved calculations share a formula but can
  use different dates or records.
- **Partial use:** known production and freight can be calculated, but handling,
  net benefit and unused-material disposition still need agreed rules.
- **Remaining integration:** comparison, saving, selection, transfer creation and
  UI connections are not yet a complete end-to-end workflow.

The immediate priority is to make recommendations executable and forecast results
reproducible. Existing validation and missing-data behaviour remain in force
until the team agrees and tests changes.
