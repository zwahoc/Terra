# 00 — Product brief

Terra is an AI-assisted construction material reuse prototype for a single operator. It turns project documents into reviewed material information, identifies compatible cross-project reuse opportunities, tracks their execution and reports comparative environmental estimates.

## Purpose

A project may hold unused materials while another needs equivalent products. Terra connects the evidence, identities, quantities and timing needed to evaluate that opportunity. It does not assert that a particular company lacks existing systems or that its inventory is accessible to Terra.

## Capabilities

| Capability | Operator outcome |
|---|---|
| Document ingestion | Upload related files, inspect extracted project/material facts and compare them with Terra's existing records. |
| Review and publication | Correct disagreements, resolve uncertainty, approve each file and publish one complete batch. |
| Matching | Compare reuse, deadline and carbon alternatives for reviewed catalogue identities and eligible source/recipient quantities. |
| Transfers | Confirm/reserve an individual transfer, record full dispatch/receipt and positive partial or repeated use. |
| Reporting | Inspect current actual-use carbon estimates, missing inputs, calculation evidence and CSV/JSON exports. |

The interface has Home, Inventory, Matching, Approvals, Deliveries, Upload and Report pages, plus a separate model-comparison sandbox. Uploaded files may cover multiple projects. Manual submissions remain operator-provided rather than document-supported.

## Boundaries

- One operator, no application accounts, login, users or role tables. Server-side database access still requires protection.
- AI interprets and proposes. Python validates quantities, computes balances and controls operational writes.
- Publication is batch-wide; file approval and publication are separate. High model confidence never replaces approval.
- Material identity/specifications, units, release, condition, suitability, traceability, quantities and timing govern matching. A category label alone does not exclude a reviewed identity.
- Reservations, dispatch, receipt and actual use are distinct. Forecasts and competing plans are not achieved reuse.
- The application runs locally through React → FastAPI → Python services → named SQL Connect REST operations. Cloud hosting/authentication is not configured.

## Exclusions

No live SDP ERP/BIM/Pantas integration, real logistics execution or payments, material-price tracking, financial-savings calculation, full lifecycle assessment, engineering certification, carbon credits, automatic official GHG deductions, expanded damage/return management or enterprise access-control system is included.

The canonical seed and illustrative factors are demonstration data. Real document interpretation and material suitability require human verification. Source provenance and environmental limitations remain visible even when fixture-origin notes are kept outside model context.

Requirements: [SRS](TERRA_SRS_v1.0.md). Workflow: [Document 01](01_BUSINESS_WORKFLOW.md). Architecture: [Document 09](09_ARCHITECTURE_UPDATE.md).
