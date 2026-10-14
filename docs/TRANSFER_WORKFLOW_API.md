# Terra transfer workflow API and Postman guide

This local milestone implements transfer work from approval through confirmed
use. All records and writes use Terra's loopback-only SQL Connect
emulator. JSON records are never a fallback; response metadata still identifies
the immutable synthetic baseline.

## Quantity and transition contract

The supported path is `APPROVED -> RESERVED -> IN_TRANSIT -> RECEIVED ->
REUSED`. `APPROVED` and `RESERVED` may instead become `CANCELLED`; cancellation
after dispatch is rejected.

Reservation, dispatch, and receipt have no quantity field. Reservation holds
the full `approved_quantity` once. Dispatch reads the current
`reserved_quantity` from the emulator and moves all of it atomically. Receipt
reads the current `dispatched_quantity` and confirms all of it arrived. A
supplied dispatch or receipt `quantity` is explicitly rejected with HTTP 422
rather than ignored. Each confirm-use request contains one positive integer
increment, capped by `received_quantity - actually_used_quantity`. Confirm-use
can be repeated with a new idempotency key; the transfer remains `REUSED` and
the stored used quantity and demand counters increase exactly once per request.

One full receipt is an intentional MVP restriction: this endpoint cannot record
a partial or missing delivery. Disposition of a partially used remainder remains
undefined. An approved-but-not-used remainder stays in
`committed_incoming_quantity`; `REUSED` confirms only the used quantity. No
return or release is invented. Legacy/runtime rows with partial dispatch or
partial receipt state are not rewritten; a new operation is rejected pending
an explicit resolution policy, preserving all existing quantities.

Every write stores an operation fingerprint and event atomically. An identical
retry returns HTTP 200 with `replayed: true`; changed input with the same
`idempotency_key` returns HTTP 409.

## Start, reset, and common Postman settings

From `D:\Terra`, use separate terminals:

```powershell
npm run emulator
npm run seed
npm run dev:backend
```

Reset runtime changes with:

```powershell
npm run seed:reset -- --confirm demo-terra-local
npm run seed:verify
```

In Postman use Authorization `No Auth`, header `Content-Type: application/json`,
raw JSON bodies, and base URL `http://127.0.0.1:8000`. Use a new idempotency key
for every different write; retain a key only to test an identical replay.

`TRF-001` / `ALC-007` is verified on 2026-10-13: `SUP-011` and `DEM-010`
have matching `MAT-018`/`pcs`, eligible confirmed states, date windows covering
the test date, and 250 pcs capacity. The sequence below uses 200 pcs.

## Complete positive sequence

Approve: `POST /api/transfers/TRF-001/approve`

```json
{"approved_quantity":200,"source_confirmation_status":"CONFIRMED","destination_confirmation_status":"CONFIRMED","actor_label":"Demo operator","idempotency_key":"postman-trf001-approve-001","evidence_ref":"SYNTHETIC Postman approval"}
```

Reserve the complete approved quantity: `POST /api/transfers/TRF-001/reserve`

```json
{"actor_label":"Demo operator","idempotency_key":"postman-trf001-reserve-001","evidence_ref":"SYNTHETIC Postman reservation"}
```

Dispatch: `POST /api/transfers/TRF-001/dispatch`

```json
{"actor_label":"Demo operator","idempotency_key":"postman-trf001-dispatch-001","evidence_ref":"SYNTHETIC Postman dispatch"}
```

Immediately after dispatch, GET read-back shows transfer status `IN_TRANSIT`,
`reserved_quantity: 0`, and `dispatched_quantity: 200`; `SUP-011` shows
`reserved_active_quantity: 0` and `transferred_out_quantity: 200`. The
`DISPATCHED` event payload contains `quantity: 200`. `DEM-010` still has its
200-unit incoming commitment and is not fulfilled by dispatch.

Receive: `POST /api/transfers/TRF-001/receive`

```json
{"actor_label":"Demo operator","idempotency_key":"postman-trf001-receive-001","evidence_ref":"SYNTHETIC Postman full receipt"}
```

Immediately after receipt, GET read-back shows transfer status `RECEIVED`,
`received_quantity: 200`, `actually_used_quantity: 0`, and a non-null
`delivered_at` timestamp with an offset. Source counters are unchanged from
dispatch. `DEM-010` remains unfulfilled with a 200-unit incoming commitment,
and the single `RECEIVED` event payload contains `quantity: 200`. Receipt does
not confirm use.

Confirm use (this example uses the complete quantity in one request):
`POST /api/transfers/TRF-001/confirm-use`

```json
{"quantity":200,"actor_label":"Demo operator","idempotency_key":"postman-trf001-use-001","evidence_ref":"SYNTHETIC Postman use confirmation"}
```

Each response is HTTP 200 with Terra's `{data, meta, error}` envelope. `data`
contains `transfer`, the appended `event`, current `supply_offer`, current
`demand_request`, `idempotency_key`, and `replayed`. Final expectations are:

- transfer `REUSED`; approved/dispatched/received/used 200; reserved 0;
- `SUP-011`: reserved active 0, transferred out 200;
- `DEM-010`: fulfilled 200, committed incoming 0, uncommitted 50;
- events: `REQUESTED, APPROVED, RESERVED, DISPATCHED, RECEIVED, USED`.

Read back with `GET /api/transfers/TRF-001`, `GET
/api/transfers/TRF-001/events`, `GET /api/supply-offers/SUP-011`, and `GET
/api/demand-requests/DEM-010`.

To verify repeated partial use instead, reset and run the same workflow, then
confirm 120 pcs with key `postman-trf001-use-part-001` and 50 pcs with key
`postman-trf001-use-part-002`. Read-back must show 170 used, 170 fulfilled,
30 committed incoming, 80 uncommitted demand, and two `USED` events carrying
increments 120 and 50. A later actual-impact calculation intentionally has an
undefined processing allocation while used quantity is below the 200 pcs moved.

## Replay, negative, cancellation, and availability tests

Repeat a successful body unchanged: expect 200, `replayed: true`, and no extra
event/counter change. Reuse its key after changing an accepted input (such as
actor, reason, evidence, or confirm-use quantity): expect 409
`IDEMPOTENCY_KEY_REUSED`.

- Adding `"quantity": 200` to a dispatch or receipt body produces HTTP 422
  `REQUEST_VALIDATION_ERROR`; both quantities are server-derived.
- Zero/decimal/string/missing confirm-use quantities produce 422 DTO errors (or
  400 for a service-level invalid quantity).
- A zero/inconsistent reservation, a second dispatch with a new key, or an
  already partially dispatched row is HTTP 409. A zero dispatch, remaining
  reservation, prior/partial receipt, or second receipt with a new key is also
  HTTP 409. Use above received is HTTP 400. Other wrong stages and unavailable
  stock/demand/dates are HTTP 409.
- Unknown transfer IDs are HTTP 404.
- Stop the emulator but leave FastAPI running: expect HTTP 503 and no snapshot
  fallback. Restart, reseed, and use fresh keys.

For cancellation, reset/reseed, approve and reserve with fresh keys, then `POST
/api/transfers/TRF-001/cancel`:

```json
{"reason":"Synthetic Postman cancellation test","actor_label":"Demo operator","idempotency_key":"postman-trf001-cancel-001","evidence_ref":"SYNTHETIC Postman cancellation"}
```

Expect `CANCELLED`, one event, and both holds released exactly once. To test the
boundary, reset and run through dispatch before cancelling; expect HTTP 409 and
unchanged post-dispatch counters.

HTTP 404 means an unknown ID; 405 means the path exists but not that method;
500 means provider data/programming or transaction verification failed; 503
means the emulator is unavailable. Postman `ECONNREFUSED` means FastAPI itself
is not listening at port 8000.
