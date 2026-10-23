# Carbon calculation and reporting API

Terra compares hypothetical equivalent-new-material production avoidance with additional road freight and combined loading/unloading. It preserves original proposal forecasts, chosen-quantity confirmation forecasts and immutable actual-use revisions separately. It does not issue credits, deduct official inventories or implement a live Pantas exchange.

## Inputs and applicability

Required context is the specific material/catalogue unit, quantity assessed, quantity moved/processed, documented weight where mass is needed, route distance and applicable versioned factors. Null is not zero. A factor must match type, supported unit, lifecycle boundary, valid_from≤activity date, dataset version and transport mode where relevant.

Factor specificity is exact material, then explicitly applicable category, then general factor. The newest applicable valid_from wins within specificity; tied factors are ambiguous and unusable. An unfamiliar material category does not prevent operational matching, but does not create factor coverage either.

| Component | Compatible unit/basis |
|---|---|
| Production | kgCO2e per catalogue unit, or kgCO2e/kg with supported material weight |
| Road freight | kgCO2e/t-km; moved quantity×kg per catalogue unit÷1000×road km |
| Combined handling | kgCO2e per moved catalogue unit, or explicit kg basis |

Incompatible factor dimensions do not become known components by fallback. `calculation_policy_version=catalogue-unit-factors-v2` binds current dependencies/source inputs. Historical incompatible estimates stay in history and are excluded from current lists/exports.

Weight/route/master corrections require explicit operator confirmation/basis. Emission-factor dataset preparation remains separate from ingestion; an uploaded annex is evidence, not automatic reference-factor registration. Demonstration assumptions remain marked `is_demo_factor`; no real EPD/source/route verification may be invented.

## Arithmetic

```text
avoided_production = used_quantity × production_per_catalogue_unit
or used_quantity × mass_kg_per_unit × production_per_kg

additional_freight = moved_quantity × mass_kg_per_unit / 1000
                    × distance_km × freight_per_tonne_km

additional_handling = moved_quantity × handling_per_catalogue_unit
or moved_quantity × mass_kg_per_unit × handling_per_kg

net_avoided = avoided_production - additional_freight - additional_handling
```

Proposal previews use proposed quantity as moved/processed quantity. Actual production uses actually used quantity; actual freight/handling use the full dispatched quantity, including during partial use. Do not prorate all transport away because some received material is unused. Known components can be retained while net remains null if any required input is missing.

The engine boundary is:

```text
Hypothetical production substitution; extra road freight and per-piece handling. Excludes baseline freight/disposal, credits and official inventory.
```

The retained wording is an exact factor-selection value; broader runtime units still require compatible dimensions. Baseline substitution must describe equivalent new procurement displaced, not assume every material transfer is waste diversion. Negative net is possible. Carbon allocation excludes negative/unscored pairs under its objective policy, while operational eligibility can remain valid.

## Read-only forecasts

`POST /api/impact-assessments/forecast-preview` accepts supply_offer_id, demand_request_id, positive exact quantity, planning_date and factor_dataset_version. It validates one current eligible pair/cap, takes detached shared context and returns components/net, missing_data, status, factor snapshots/IDs, input hashes, boundary and assumptions with preview=true/persisted=false. It never publishes or reserves.

`POST /api/optimisation-runs/preview` accepts objective MAX_REUSE/EARLIEST_DEADLINE/MAX_NET_CO2E_AVOIDED, planning_date, factor_dataset_version and optional destination_project_id. It computes a plan and assesses each selected quantity with the same frozen context. [Comparison API](OPTIMISATION_COMPARISON_API.md) describes all three alternatives.

Planning date must cover the timestamps in supplied records. Use the applicable current date after live operations; baseline 2026-10-12 is only for the corresponding historical fixture state. Preview activity-date applicability is bound to planning_date.

## Saved calculation commands

| POST route | Scope |
|---|---|
| /api/impact-assessments/proposals/{proposal_id}/calculate | Versioned proposal forecast |
| /api/impact-assessments/transfers/{transfer_id}/calculate | Versioned actual-confirmed-use scope; delegates to durable current update where present |

Body fields are idempotency_key, revision_reason and actor_label. Changed payload/key reuse and stale source/head revisions fail; unchanged fingerprints are replay-safe. No calculation endpoint records receipt or physical use. Initial saved forecasts accompany persisted optimisation results, while confirmation retains its own chosen-quantity forecast in events.

## Automatic actual-use revisions

Confirmed use/applicable confirmed corrections atomically enqueue ImpactRefreshIntent. The local worker checks operational source revision, intent token, current head, transfer quantities/time and factor context before inserting an immutable assessment and advancing its head/completing the intent together.

GET /api/impact-refresh returns current intent status; POST /api/impact-refresh/retry reprocesses unfinished/failed work without repeating use. Newer tokens supersede older unfinished work. Unchanged current-policy inputs can complete without an extra revision. A calculation failure preserves physical facts; older estimates awaiting refresh are not current or exportable.

A COMPLETED intent may have calculation_status=INSUFFICIENT_DATA and null net; completed processing is not proof of complete reference inputs. DEMO uses illustrative factors, PRELIMINARY indicates an estimate under its retained provenance. Status does not turn a comparative estimate into certified performance.

## Read and export

- GET /api/impact-assessments supports basis, proposal/transfer filters and current_only. Current selection uses authoritative heads and pending-state/unit checks.
- GET /api/impact-assessments/{assessment_id} reads a retained revision/history with provenance.
- GET /api/exports/impact accepts basis, format=csv/json and optional project_id/transfer_id. Source/current guards prevent an inconsistent export; pending/failed actual updates exclude stale results.

An assessment retains basis, proposal/transfer ID, quantity_assessed/unit, baseline_description, production/freight/handling/net components, factor IDs/snapshots, assumptions, status and calculated_at. Actual revisions also retain source_input, revision number/previous identity/reason and the declared cost-allocation basis. Forecast and actual scopes are not summed. Global actual metrics count each transfer's used quantity once; unlike quantity units stay separate.

Report presents current project/material/route and actual-use values. Missing-input labels can be deduplicated/readable, but original codes and IDs remain inspectable. Numerical graphics must not plot unknown as zero. Demonstration-factor/boundary disclosures remain available.

## Sources

[Carbon engine](../backend/app/domain/carbon.py), [forecast calculator](../backend/app/services/forecast_preview_service.py), [impact service](../backend/app/services/impact_service.py), [automatic processing](../backend/app/services/automatic_impact_service.py), [export](../backend/app/services/impact_export_service.py), [schemas](../backend/app/schemas/impact.py), [routes](../backend/app/routes/impact.py). Local/schema/unit tests do not prove missing real-world factors or environmental assurance.
