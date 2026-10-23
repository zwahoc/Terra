# Terra seed data dictionary

This canonical-fixture mapping supplements the [logical field meanings in Document 02](02_DATA_MODEL_CONTRACT.md). It does not replace the domain contract. The canonical fixture is [data/terra_seed.json](../data/terra_seed.json), version 1.0.0, snapshot 2026-10-12, all synthetic.

There are exactly 13 entity arrays plus metadata. Metadata stays in the JSON/API envelope and is not an extra database table. Each ID is an explicit string primary key. IDs do not use an auth identity or implicit UUID. PostgreSQL tables use the entity names below. GraphQL field casing is explicit; @col names match the JSON snake_case keys, including kgco2e suffixes. Nested JSON keys remain snake_case.

The tables below describe the portable seed values and their field mappings. Seed quantity values are whole pcs; current runtime SQL quantity fields use Int64 millionths and runtime material category/unit fields permit strings. These are distinct validation layers, not contradictory new seed values. Read [Document 02](02_DATA_MODEL_CONTRACT.md) for exact encoding and provider-only intake/publication/matching/impact records.

Dates are ISO YYYY-MM-DD, timestamps preserve +08:00 instants, and JSON objects remain ordinary-unit evidence. Provider floating values apply to weight/distance/factors/results, not authoritative stock. Historical fixture events and quantities are not a claim that current controls support creating partial shipments.

Foreign keys have actual @ref relationships and database constraints. Optional references default to Firebase generated SET NULL behavior and required references to CASCADE; admin deletion is for local reset only and is not a business/audit deletion API. `projects.code` and `transfers.proposal_id` also have unique constraints. `impact_assessments.factor_ids` is a logical reference array validated offline, not an SQL FK array; it may later be normalized without changing the portable JSON.

The separate [integrated demo](DEMO_WORKSPACE.md) uses the same 13 entity collections with runtime category/unit validation and date-relative scenario values. Its counts differ from the canonical counts below.

## projects

5 rows. GraphQL type `Project`, list query `projects`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `code` | `code` | str | no |
| `name` | `name` | str | no |
| `township` | `township` | str | no |
| `location` | `location` | json | yes |
| `start_date` | `startDate` | date | yes |
| `target_end_date` | `targetEndDate` | date | yes |
| `status` | `status` | ProjectStatus: ACTIVE, COMPLETED | no |
| `managing_organisation` | `managingOrganisation` | str | no |

## materials

20 rows. GraphQL type `Material`, list query `materials`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `category` | `category` | Seed category: PAVING_BLOCK, BRICK, TILE; runtime string | no |
| `canonical_name` | `canonicalName` | str | no |
| `specifications` | `specifications` | json | no |
| `standard_unit` | `standardUnit` | Seed unit: pcs; runtime string | no |
| `mass_kg_per_unit` | `massKgPerUnit` | float | yes |
| `mass_source` | `massSource` | str | yes |
| `reference_code` | `referenceCode` | str | yes |
| `is_synthetic` | `isSynthetic` | bool | no |

## documents

15 rows. GraphQL type `Document`, list query `documents`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `project_id` | `projectId` | string FK → projects.id | no |
| `document_type` | `documentType` | DocumentType: BOQ, PURCHASE_ORDER, INVENTORY, DEMAND, OTHER | no |
| `display_filename` | `displayFilename` | str | no |
| `file_uri` | `fileUri` | str | yes |
| `file_hash` | `fileHash` | str | yes |
| `source_availability` | `sourceAvailability` | SourceAvailability: METADATA_ONLY, FILE_AVAILABLE | no |
| `processing_status` | `processingStatus` | ProcessingStatus: SIMULATED, QUEUED, PROCESSED, FAILED, REVIEWED | no |
| `recorded_at` | `recordedAt` | timestamp | no |
| `is_simulated` | `isSimulated` | bool | no |

## extracted_rows

50 rows. GraphQL type `ExtractedRow`, list query `extractedRows`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `document_id` | `documentId` | string FK → documents.id | no |
| `source_locator` | `sourceLocator` | str | no |
| `raw_description` | `rawDescription` | str | no |
| `raw_quantity` | `rawQuantity` | str | no |
| `raw_unit` | `rawUnit` | str | no |
| `parsed_fields` | `parsedFields` | json | no |
| `suggested_material_id` | `suggestedMaterialId` | string FK → materials.id | yes |
| `confidence_score` | `confidenceScore` | float | yes |
| `review_status` | `reviewStatus` | ReviewStatus: PENDING, ACCEPTED, CORRECTED, REJECTED | no |
| `review_mode` | `reviewMode` | ReviewMode: DEMO_PREAPPROVED, PENDING_DEMO, MANUAL_CORRECTION | no |
| `is_simulated` | `isSimulated` | bool | no |

## supply_offers

22 rows. GraphQL type `SupplyOffer`, list query `supplyOffers`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `source_project_id` | `sourceProjectId` | string FK → projects.id | no |
| `material_id` | `materialId` | string FK → materials.id | no |
| `origin_document_row_id` | `originDocumentRowId` | string FK → extracted_rows.id | yes |
| `declared_quantity` | `declaredQuantity` | int | no |
| `confirmed_quantity` | `confirmedQuantity` | int | yes |
| `reserved_active_quantity` | `reservedActiveQuantity` | int | no |
| `transferred_out_quantity` | `transferredOutQuantity` | int | no |
| `unit` | `unit` | Seed unit: pcs; runtime string | no |
| `surplus_status` | `surplusStatus` | SurplusStatus: POTENTIAL, CONFIRMED, SUSPENDED, CLOSED | no |
| `condition` | `condition` | Condition: UNUSED, RECOVERED, UNKNOWN | no |
| `available_from` | `availableFrom` | date | no |
| `available_until` | `availableUntil` | date | yes |
| `batch_or_lot_code` | `batchOrLotCode` | str | yes |
| `material_owner_label` | `materialOwnerLabel` | str | yes |
| `evidence_refs` | `evidenceRefs` | array | no |

## demand_requests

22 rows. GraphQL type `DemandRequest`, list query `demandRequests`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `destination_project_id` | `destinationProjectId` | string FK → projects.id | no |
| `material_id` | `materialId` | string FK → materials.id | no |
| `origin_document_row_id` | `originDocumentRowId` | string FK → extracted_rows.id | yes |
| `required_quantity` | `requiredQuantity` | int | no |
| `fulfilled_quantity` | `fulfilledQuantity` | int | no |
| `unit` | `unit` | Seed unit: pcs; runtime string | no |
| `needed_from` | `neededFrom` | date | no |
| `required_by` | `requiredBy` | date | no |
| `request_status` | `requestStatus` | RequestStatus: OPEN, FULFILLED, CANCELLED | no |
| `is_outstanding_need_confirmed` | `isOutstandingNeedConfirmed` | bool | no |

## route_distances

10 rows. GraphQL type `RouteDistance`, list query `routeDistances`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `from_project_id` | `fromProjectId` | string FK → projects.id | no |
| `to_project_id` | `toProjectId` | string FK → projects.id | no |
| `distance_km` | `distanceKm` | float | no |
| `assumption_type` | `assumptionType` | RouteAssumption: SIMULATED_ROAD_DISTANCE | no |
| `transport_mode` | `transportMode` | TransportMode: ROAD_FREIGHT | no |
| `is_synthetic` | `isSynthetic` | bool | no |

## optimisation_runs

4 rows. GraphQL type `OptimisationRun`, list query `optimisationRuns`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `created_at` | `createdAt` | timestamp | no |
| `objective` | `objective` | Objective: MAX_REUSE, MAX_NET_CO2E_AVOIDED, EARLIEST_DEADLINE | no |
| `inputs_snapshot_hash` | `inputsSnapshotHash` | str | no |
| `input_snapshot` | `inputSnapshot` | json | no |
| `factor_dataset_version` | `factorDatasetVersion` | str | no |
| `solver_status` | `solverStatus` | SolverStatus: SUCCEEDED, INFEASIBLE, FAILED | no |
| `assumptions` | `assumptions` | json | no |

## allocation_proposals

15 rows. GraphQL type `AllocationProposal`, list query `allocationProposals`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `run_id` | `runId` | string FK → optimisation_runs.id | no |
| `supply_offer_id` | `supplyOfferId` | string FK → supply_offers.id | no |
| `demand_request_id` | `demandRequestId` | string FK → demand_requests.id | no |
| `proposed_quantity` | `proposedQuantity` | int | no |
| `unit` | `unit` | Seed unit: pcs; runtime string | no |
| `compatibility_result` | `compatibilityResult` | Compatibility: ELIGIBLE, REVIEW_REQUIRED, INELIGIBLE | no |
| `status` | `status` | ProposalStatus: PROPOSED, SELECTED, REJECTED, EXPIRED | no |
| `reason_codes` | `reasonCodes` | array | no |
| `created_at` | `createdAt` | timestamp | no |

## transfers

8 rows. GraphQL type `Transfer`, list query `transfers`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `proposal_id` | `proposalId` | string FK → allocation_proposals.id | no |
| `approved_quantity` | `approvedQuantity` | int | no |
| `reserved_quantity` | `reservedQuantity` | int | no |
| `dispatched_quantity` | `dispatchedQuantity` | int | no |
| `received_quantity` | `receivedQuantity` | int | no |
| `actually_used_quantity` | `actuallyUsedQuantity` | int | no |
| `status` | `status` | TransferStatus: REQUESTED, APPROVED, RESERVED, IN_TRANSIT, RECEIVED, REUSED, CANCELLED | no |
| `source_confirmation_status` | `sourceConfirmationStatus` | Confirmation: PENDING, CONFIRMED, DECLINED | no |
| `destination_confirmation_status` | `destinationConfirmationStatus` | Confirmation: PENDING, CONFIRMED, DECLINED | no |
| `requested_at` | `requestedAt` | timestamp | no |
| `delivered_at` | `deliveredAt` | timestamp | yes |
| `reuse_confirmed_at` | `reuseConfirmedAt` | timestamp | yes |
| `notes` | `notes` | str | yes |

## transfer_events

31 rows. GraphQL type `TransferEvent`, list query `transferEvents`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `transfer_id` | `transferId` | string FK → transfers.id | no |
| `event_type` | `eventType` | EventType: REQUESTED, APPROVED, RESERVED, DISPATCHED, RECEIVED, USED, CANCELLED, CORRECTION | no |
| `occurred_at` | `occurredAt` | timestamp | no |
| `actor_label` | `actorLabel` | str | no |
| `payload` | `payload` | json | no |
| `evidence_ref` | `evidenceRef` | str | yes |

## emission_factors

8 rows. GraphQL type `EmissionFactor`, list query `emissionFactors`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `factor_type` | `factorType` | FactorType: NEW_MATERIAL_PRODUCTION, TRANSPORT, PROCESSING | no |
| `material_id` | `materialId` | string FK → materials.id | yes |
| `material_category` | `materialCategory` | Seed category: PAVING_BLOCK, BRICK, TILE; runtime string | yes |
| `transport_mode` | `transportMode` | TransportMode: ROAD_FREIGHT | yes |
| `value` | `value` | float | no |
| `unit` | `unit` | str | no |
| `source_label` | `sourceLabel` | str | no |
| `source_url` | `sourceUrl` | str | yes |
| `geography` | `geography` | str | no |
| `lifecycle_boundary` | `lifecycleBoundary` | str | no |
| `version` | `version` | str | no |
| `valid_from` | `validFrom` | date | no |
| `is_demo_factor` | `isDemoFactor` | bool | no |

## impact_assessments

8 rows. GraphQL type `ImpactAssessment`, list query `impactAssessments`.

| JSON field | GraphQL field | Type / permitted values | Nullable |
|---|---|---|---|
| `id` | `id` | string PK | no |
| `basis` | `basis` | ImpactBasis: PROPOSAL_FORECAST, ACTUAL_CONFIRMED_USE | no |
| `proposal_id` | `proposalId` | string FK → allocation_proposals.id | yes |
| `transfer_id` | `transferId` | string FK → transfers.id | yes |
| `quantity_assessed` | `quantityAssessed` | int | no |
| `unit` | `unit` | Seed unit: pcs; runtime string | no |
| `baseline_description` | `baselineDescription` | str | no |
| `avoided_production_kgco2e` | `avoidedProductionKgco2E` | float | yes |
| `additional_transport_kgco2e` | `additionalTransportKgco2E` | float | yes |
| `additional_processing_kgco2e` | `additionalProcessingKgco2E` | float | yes |
| `net_avoided_kgco2e` | `netAvoidedKgco2E` | float | yes |
| `factor_ids` | `factorIds` | array | no |
| `assumptions` | `assumptions` | json | no |
| `calculation_status` | `calculationStatus` | CalculationStatus: DEMO, PRELIMINARY, INSUFFICIENT_DATA, REVIEWED | no |
| `calculated_at` | `calculatedAt` | timestamp | no |

## JSON subcontracts and units

- `materials.specifications` includes positive mm dimensions and category-specific material type, colour, finish, grade/intended use. Different critical specs have distinct catalogue IDs. Demo grades/slip labels assert no certification.
- `extracted_rows.parsed_fields` contains `record_kind`, integer canonical `quantity`, `unit`, specifications and effective date. Corrected ROW-048 also preserves a correction object and the raw `12O` text. Document type and project are resolved through document_id.
- `optimisation_runs.input_snapshot` contains as_of, supplies, demands, materials, routes and factor dataset version. The hash uses sorted-key compact JSON encoded as UTF-8. Each historical plan is validated against that snapshot; current counters reflect later transfers.
- `transfer_events.payload` stores synthetic=true and stage quantity, not an instruction to replay deltas during import. Partial-use USED events additionally record unresolved_quantity. Event histories are complete and chronological.
- `impact_assessments.assumptions` states route ID/distance, mass, moved quantity, road-freight mode, substitution ratio, omissions, handling allocation and synthetic flag. Production uses quantity_assessed; freight uses moved_quantity. Missing components produce null net and INSUFFICIENT_DATA.
- Production factors use kgCO2e/pcs; transport uses kgCO2e/t-km; handling uses kgCO2e/pcs. Factors are synthetic demo-v1, valid from 2026-09-01, with no invented source URLs.

## Derived values

`reservable = confirmed - active_reserved - dispatched` for confirmed UNUSED supply within its availability window; otherwise zero. Negative counters are validation errors, not hidden by clamping.

`remaining_unfulfilled = required - actual_fulfilled`. `newly_allocatable = required - actual_fulfilled - incoming_commitments` only for confirmed OPEN demand. Commitments begin at reservation, decrease on actual use, and remain through receipt/partial use. Requested/approved/cancelled-before-dispatch records contribute zero.

Confirmed reuse mass sums transfer actual-use quantities once, multiplied by known material mass. The baseline has 950 used pavers, 2.375 t. Project count includes both source and destination, yielding 3. Actual net carbon totals include complete actual assessments only, 291.04 kgCO2e, with incomplete IMP-005 reported separately. Forecast rows and alternative runs are never added to actual results.

The enum REUSED means positive recorded use in this fixture; it is not sufficient to release unresolved residual promises. Current lifecycle/revision semantics are in Documents 01/02. The validator/importer protect this baseline; application commands additionally use guarded operational transactions.

## Maintenance

Generate/check the immutable fixture with `scripts/generate_seed.py --check`; validate with `npm run seed:validate`. Provider schema/operations come from the shared registry/generator. Do not regenerate or reseed an active workspace as documentation cleanup. [Seed specification](03_SEED_DATABASE_SPEC.md) defines scenario coverage, and [Local development](LOCAL_DEVELOPMENT.md) separates new empty setup from protected persistence/recovery.
