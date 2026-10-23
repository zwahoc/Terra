# Transfer API and lifecycle

The normal workflow confirms and reserves an individual current proposal in one atomic command. Approval of an ingestion file is a separate action. All routes use the loopback FastAPI boundary and named SQL Connect transactions; JSON files are not a live operational fallback.

## Read and preview

| Method/path | Purpose |
|---|---|
| GET /api/transfers | List persisted transfers |
| GET /api/transfers/{transfer_id} | Read one transfer |
| GET /api/transfers/{transfer_id}/events | Inspect immutable event history |
| GET /api/supply-offers/{offer_id} | Read source/available quantity context |
| GET /api/demand-requests/{demand_id} | Read requirement/fulfilment/incoming commitments |
| GET /api/allocation-proposals/{proposal_id}/confirmation-preview | Read fresh chosen-quantity timing, revision and forecast |

Preview query fields are quantity and generation_id. The result includes proposal/generation IDs, original/chosen quantity, expected_revision, unit, confirmable, earliest_start, arrival_date and chosen-quantity forecast. It creates no transfer/hold. Frontend automatic preview after quantity changes does not imply approval.

Only eligible current-generation source/recipient pairs can proceed. A disappearing pair is not replaced by another automatically. Confirmation checks date/dependency currency even if a previous preview was valid. Earliest reservation/dispatch is on/after planning date, source available_from and recipient needed_from, with arrival before required_by and dispatch inside source availability.

## Combined confirmation/reservation

`POST /api/allocation-proposals/{proposal_id}/confirm`

| Field | Contract |
|---|---|
| quantity | Positive exact integer/decimal-string value, no more than the current proposed cap; catalogue granularity applies |
| generation_id | Current selected material generation, returned by matching |
| expected_revision | Fresh revision returned by preview |
| actor_label | Nonempty workflow audit label, not an authenticated account |
| idempotency_key | Stable key for this command and unchanged retries |
| evidence_ref | Optional operator evidence reference |

The transaction rechecks proposal/identity/specification/unit/release/condition/traceability, source and recipient budgets, suitability confirmation, timing and expected revision/generation. It creates a RESERVED transfer, approval/reservation events, coupled holds, forecast provenance and required current-head/matching state together. It does not dispatch anything.

The operator explicitly confirms suitability/release/recipient/quantity. Reducing quantity requires a fresh preview. Increasing beyond the proposal or changing recipient requires recalculation. To change a reserved quantity, cancel before dispatch and confirm a fresh recommendation; do not amend a hold in place.

Response data contains transfer, event, supply_offer, demand_request, idempotency_key and replayed. Changed input with an existing key fails; duplicate/late/stale writes cannot double reserve. A lost response requires saved-result lookup/same-command identity rather than blindly changing preview inputs and issuing another command.

## Physical actions

The base body is actor_label, idempotency_key and optional evidence_ref. The server reads current quantities; callers cannot send new counters.

| POST path | Additional fields | Allowed effect |
|---|---|---|
| /api/transfers/{id}/dispatch | None | RESERVED: move the full active reservation into dispatched quantity; hold decreases once |
| /api/transfers/{id}/receive | None | IN_TRANSIT: confirm the full dispatched quantity received |
| /api/transfers/{id}/confirm-use | quantity | RECEIVED/REUSED: add a positive exact use increment, no greater than received-minus-used |
| /api/transfers/{id}/cancel | reason | Pre-dispatch only: release source and recipient holds once, record cancellation |

```text
RESERVED → IN_TRANSIT → RECEIVED → REUSED
    ↘ CANCELLED                ↖ further valid use increments
```

No extra Reserve click is required after combined confirmation. Full dispatch/full receipt are the current physical contract. Partial shipment, shortage, return/damage/discard or post-dispatch reversal resolution is not implemented; do not mark incomplete arrival as full receipt.

Used≤received≤dispatched≤approved≤proposed and reserved+dispatched≤approved. Incoming commitments persist until actual use/pre-dispatch cancellation. Received-but-unused material stays with the recipient and may be used later; it is not automatically returned or re-offered. Transfer notes preserve operator text; event payloads/quantity fields record current/historical residuals.

## Impact and navigation

Use commits physical facts and an impact-refresh intent atomically. Automatic assessment processing creates a new current immutable revision when needed. Pending/failed carbon processing does not undo use and excludes stale current figures from reporting. Retry impact does not repeat a physical-use command.

The UI opens the exact reserved delivery and can navigate from it to the corresponding project/transfer report. Sidebar entry opens a fresh delivery list, while contextual Back returns to the list. Buttons and navigation never replace server guards.

## Legacy compatibility

The following remain for historical/unmarked proposals/requests, not new automatically generated plans:

- POST /api/allocation-proposals/{proposal_id}/approve: request-only creation of a REQUESTED transfer, no holds.
- POST /api/transfers/{transfer_id}/approve: validates approved_quantity and source/destination confirmation states, no reservation.
- POST /api/transfers/{transfer_id}/reserve: reserves the full legacy approved amount with coupled current checks.

Current generated proposals reject the request-only route with COMBINED_CONFIRMATION_REQUIRED. REQUESTED/APPROVED records retain original history and are never silently promoted. The legacy approve request uses positive strict integer approved_quantity, confirmation states, actor_label/idempotency_key/evidence_ref; it is not the broad-unit current confirmation DTO.

## Sources and verification

[Transfer schemas](../backend/app/schemas/transfers.py), [routes](../backend/app/routes/transfers.py), [confirmation service](../backend/app/services/transfer_confirmation_service.py), [workflow service](../backend/app/services/transfer_workflow_service.py), [generated transaction definitions](../terra/transfer_runtime_provider.py). Tests cover rollback, stale state, source/recipient contention, replay, timing and repeated use; see [requirements/testing](06_REQUIREMENTS_AND_TESTS.md). A configured test is not a claim of fresh cloud/native acceptance.
