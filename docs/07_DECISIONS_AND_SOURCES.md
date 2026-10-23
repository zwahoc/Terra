# 07 — Decisions, precedence and sources

## Authority

1. Explicit owner/team decisions govern the selected product scope.
2. [SRS](TERRA_SRS_v1.0.md) preserves stable requirements and approved clarifications.
3. [Document 09](09_ARCHITECTURE_UPDATE.md) overrides conflicting architecture descriptions.
4. Documents 00-08 and current technical guides describe their respective contracts; runtime schemas/source establish implemented transport details.
5. Legacy material, old agent handoffs, fixture narratives and local proof logs are history, not alternative specifications.

Documentation was consolidated for repository publication without changing application behaviour or the canonical seed. Original superseded material was preserved in a private verified archive. Compatibility schemas previously embedded in a report now live in `tests/fixtures/ingestion_contract_v1.json`.

## Current decisions

| Topic | Decision | Contract |
|---|---|---|
| Product/operator | Terra, one operator, no application accounts/login/roles | SRS, Document 00 |
| Runtime | React → FastAPI → independent Python → named SQL Connect REST | Document 09 |
| Local persistence | Private persistent emulator data and separate private original-source/checkpoint storage | Document 04, LOCAL_DEVELOPMENT |
| Cloud | Target SQL Connect/Cloud SQL access needs separate IAM/connectivity/cost approval; no public deployment configured | Document 09 |
| AI | LLM-led useful project/material interpretation; Terra-only controlled read/proposal tools; HIGH DeepSeek; exact explicit primary selection | Document 05 |
| Usage | Informational estimate/uncertainty ledger, no spending hard stop or implicit billing activation | Document 05 |
| Catalogue search | LLM-chosen alternative/bulk terms, complete stable pagination, no ranking/top-N suppression | Document 05 |
| Catalogue eligibility | Same reviewed specific identity and consistent specs/units; no family whitelist/default family completeness gate | Document 01, eligibility guide |
| Review | Read prepared recommendations, change disagreements, resolve blockers, approve each file once | Document 05 |
| Publication | Separate complete-batch atomic guarded publication; immutable contributions and exact predecessor supersession | Documents02/05 |
| New evidence | ADD/REPLACE/HISTORY_ONLY and explicit exclusion; manual values never claim documentary provenance | Document 05 |
| Quantities | Exact runtime millionths with encoding marker, retained source precision and supported explicit conversions | Document 02 |
| Matching | Automatic after relevant commits; all-project affected-material scopes; three current alternatives; future opportunities visible; old recommendations unusable | Matching guides |
| Execution | Individual combined confirmation/reservation; fresh checks before quantity reduction; cancel/release/fresh confirmation to change a reserved amount | Transfer guide |
| Physical stages | Full dispatch, full receipt, positive partial/repeated use; unused received material stays committed | Document 01 |
| Exceptions | No post-dispatch cancel/restock, partial shipment/shortage/return/damage resolution or dismissal in this version | SRS, Document 01 |
| Carbon | Used quantity for production, moved quantity for freight/handling; exact applicability/units; immutable revisions/current heads | Impact guide |
| Background failures | Publication/use remain saved; pending/failed calculations do not expose old estimates as current | Documents05/08 |
| UI | Desktop priority, familiar forest/sage/ochre graphics and animated sidebar with readable controls/exact handoffs | README, frontend source |
| Test sequencing | First complete integrated workflow before deferred scenario refinement; essential guards are never deferred | Document 06 |
| Seed | Preserve 13-array synthetic baseline and2026-10-12 date; owner workspace is separate | Document 03 |

## Superseded assumptions

- Parser-first/text-PDF-only intake, a mandatory chatbot, fixed source templates and one-project-per-file are not the current ingestion scope.
- Confidence-based approval, per-row immediate publication or publishing successes while failures are pending are not allowed.
- RM10 spending cutoff, forced LOW reasoning and total tool-step cutoffs were removed. Real provider/resource constraints still exist.
- Preset paver/brick/tile families and integer-pieces-only matching are seed history, not current runtime limits.
- Request→approve→reserve and whole-plan atomic execution are not the normal current transfer flow.
- Manual carbon Calculate after every saved use is replaced by durable automatic current revision processing.
- Seed-era ephemeral emulator startup/reseeding is superseded by private disk persistence. No reseed is required after restart.

## Implementation and acceptance limitations

Local named-operation/storage/transaction tests are evidence for their exercised paths, not cloud IAM or universal concurrency/scale guarantees. Model coverage checks do not prove semantic correctness. Retained old analysis is not evidence of a current primary/prompt configuration.

Provider availability/quotas, representative scans/Office semantics, malformed-output edge cases, very large catalogue latency, native accessibility, crash/upgrade recovery and deferred physical exceptions remain explicit acceptance areas. No missing stock, route, conversion, factor or engineering fact is invented to make a demo pass.

## Source references

Official references inform the selected provider design; checked-in code/configuration determines the implemented local behaviour. Recheck current provider capabilities before separately changing those integrations.

- [SQL Connect schemas](https://firebase.google.com/docs/sql-connect/schemas-guide)
- [Named query execution](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeQuery)
- [Named mutation execution](https://firebase.google.com/docs/reference/sql-connect/rest/v1/projects.locations.services.connectors/executeMutation)
- [SQL Connect mutations and transactions](https://firebase.google.com/docs/sql-connect/mutations-guide)
- [SQL Connect authorisation/security](https://firebase.google.com/docs/sql-connect/authorization-and-security)
- [SQL Connect emulator/CLI](https://firebase.google.com/docs/sql-connect/cli-reference)
- [SQL Connect pricing](https://firebase.google.com/docs/sql-connect/pricing), for later approved provisioning, not a local billing action

These links are source references, not a claim of live ERP/Pantas access, official material certification, a permanent free cloud service or production deployment.
