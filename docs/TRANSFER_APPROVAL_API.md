# Transfer approval API

`POST /api/transfers/{transfer_id}/approve` approves an existing `REQUESTED`
transfer in the local SQL Connect emulator. It does not reserve stock, create an
incoming demand commitment, dispatch, receive, record reuse, or calculate carbon.

## Contract and verified fixture

The successful baseline fixture is `TRF-001`, linked to selected and eligible
proposal `ALC-007`. The proposal is for 250 pcs, so this guide approves 200 pcs.
At baseline, the transfer is `REQUESTED`, both confirmations are `PENDING`, and
all transfer quantity counters are zero.

```json
{
  "approved_quantity": 200,
  "source_confirmation_status": "CONFIRMED",
  "destination_confirmation_status": "CONFIRMED",
  "actor_label": "Demo operator",
  "idempotency_key": "postman-approve-trf-001-001",
  "evidence_ref": "SYNTHETIC Postman approval; no physical evidence"
}
```

- `approved_quantity` is a positive integer no greater than the proposal quantity.
- Both confirmation statuses must be `CONFIRMED`.
- `actor_label` is a non-empty audit label. Terra has no application accounts,
  so it is not a verified user identity.
- `idempotency_key` is required and limited to 128 characters. An identical
  replay is safe; reuse with changed input returns HTTP 409.
- `evidence_ref` is optional free text. The current contract has no document
  upload or verified-signature model, so this is not proof of inspection,
  ownership, or authorization.

The connector's `ApproveTransfer` named mutation rechecks the transfer and
proposal, inserts the replay record, updates the transfer, and inserts one
`APPROVED` event in one transaction. A unique operation key protects concurrent
retries. Any failed step rolls back all effects.

Success uses Terra's envelope. `data` contains the complete `transfer`, complete
`event`, `idempotency_key`, and a `replayed` boolean. `meta` contains baseline
`dataset_version`, `synthetic`, and `as_of_date`; `error` is null. The first
successful call returns `replayed: false`; an identical retry returns true and
the same event ID.

Baseline metadata still comes from `data/terra_seed.json`. Live transfer, event,
and idempotency records come only from the emulator.

## Exact Postman walkthrough

Start and seed the emulator, then start FastAPI in separate terminals:

```sh
npm run emulator
npm run seed
npm run dev:backend
```

Run negative quantity and confirmation checks before the successful call, or
reset/reseed between checks, because success moves `TRF-001` out of `REQUESTED`.

Successful request:

- Method: `POST`
- URL: `http://127.0.0.1:8000/api/transfers/TRF-001/approve`
- Authorization: `No Auth`
- Header: `Content-Type: application/json`
- Body: `raw` → `JSON`, using the JSON above

Expected: HTTP 200; transfer status `APPROVED`; approved quantity 200; both
confirmations `CONFIRMED`; one `APPROVED` event; `reserved_quantity` remains 0;
`replayed` is false.

Post-response script:

```javascript
pm.test("status is 200", () => pm.response.to.have.status(200));

const body = pm.response.json();
pm.test("Terra success envelope", () => {
  pm.expect(body).to.have.keys("data", "meta", "error");
  pm.expect(body.error).to.eql(null);
  pm.expect(body.meta.synthetic).to.eql(true);
});

pm.test("approved but not reserved", () => {
  pm.expect(body.data.transfer.id).to.eql("TRF-001");
  pm.expect(body.data.transfer.status).to.eql("APPROVED");
  pm.expect(body.data.transfer.approved_quantity).to.eql(200);
  pm.expect(body.data.transfer.reserved_quantity).to.eql(0);
  pm.expect(body.data.transfer.source_confirmation_status).to.eql("CONFIRMED");
  pm.expect(body.data.transfer.destination_confirmation_status).to.eql("CONFIRMED");
  pm.expect(body.data.event.event_type).to.eql("APPROVED");
  pm.expect(body.data.event.payload.quantity).to.eql(200);
});

pm.collectionVariables.set("approval_event_id", body.data.event.id);
```

Read back with `GET http://127.0.0.1:8000/api/transfers/TRF-001`, `No Auth`, and
no body. Expect 200 and the same status, quantity, confirmations, and zero
`reserved_quantity`. Linked `SUP-011.reserved_active_quantity` and
`DEM-010.fulfilled_quantity` also remain zero; those entities have no HTTP route,
so this invariant is verified by the emulator integration test.

Replay and negative tests:

1. Repeat the identical successful POST. Expect 200, `replayed: true`, and the
   same event ID stored in `approval_event_id`.
2. Reuse that key but change quantity to 199. Expect 409 and
   `IDEMPOTENCY_KEY_REUSED`.
3. After reset/reseed, send 251 with a new key. Expect 400 and
   `APPROVED_QUANTITY_EXCEEDS_PROPOSAL`.
4. After reset/reseed, set either confirmation to `PENDING` with a new key.
   Expect 400 and `TRANSFER_CONFIRMATIONS_REQUIRED`.
5. Use `/api/transfers/TRF-999/approve` with a new key. Expect 404 and
   `TRANSFER_NOT_FOUND`.
6. After success, use a new key on `TRF-001`. Expect 409 and
   `TRANSFER_INVALID_STAGE`.
7. Omit a required field, add an unknown field, or send a non-integer quantity.
   Expect 422 and `REQUEST_VALIDATION_ERROR` in Terra's envelope.

For availability, stop the emulator with Ctrl-C while leaving FastAPI running,
then send a request with a new key. Expect 503 and `TRANSFER_DATA_UNAVAILABLE`,
with no snapshot fallback. Postman `ECONNREFUSED` means FastAPI itself is not
reachable. Restart the emulator, run `npm run seed`, and retry against the
restored baseline. HTTP 500 means FastAPI reached the provider but encountered
invalid data or an unexpected transaction/provider error; inspect server logs.
