"""Traceable JSON/CSV impact export without forecast/actual aggregation."""

from __future__ import annotations

import csv
import io
import json
from typing import Any
from terra.quantities import json_default
from backend.app.domain.carbon import assessment_factor_units_valid

from backend.app.repositories.impact_repository import (
    ImpactRepository,
    ImpactRepositoryError,
    ImpactRepositoryUnavailable,
)
from backend.app.services.impact_service import ImpactError, ImpactUnavailable, ImpactConflict, _load
from backend.app.services.transfer_read_service import load_baseline_metadata


DISCLAIMER = (
    "Comparative synthetic estimate only; not an official Scope 1/2/3 deduction, "
    "waste-diversion total, carbon credit, BCX certification, or live Pantas record."
)


def _index(rows):
    return {row["id"]: row for row in rows}


def impact_export_records(
    basis: str, repository: ImpactRepository | None = None,
    project_id: str | None = None, transfer_id: str | None = None,
) -> list[dict[str, Any]]:
    repository = repository or ImpactRepository()
    adapter=getattr(repository,'_adapter',None)
    guarded=adapter is not None and adapter.execute('GetQuantityEncoding')['quantityEncoding']
    read_version=adapter.execute('GetOperationalVersion')['operationalVersion'] if guarded else None
    snapshot = _load(repository)
    try:
        current_ids = {
            head["current_assessment_id"]
            for head in repository.list_heads()
            if head["basis"] == basis and head["current_assessment_id"] is not None
        }
    except ImpactRepositoryUnavailable as exc:
        raise ImpactUnavailable(
            "IMPACT_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable."
        ) from exc
    except ImpactRepositoryError as exc:
        raise ImpactError(
            "IMPACT_DATA_ERROR", "Current impact export selection failed."
        ) from exc
    assessments = [
        row
        for row in snapshot["impact_assessments"]
        if row["basis"] == basis and row["id"] in current_ids
        and assessment_factor_units_valid(row,snapshot["emission_factors"])
    ]
    adapter=getattr(repository,'_adapter',None)
    if adapter is not None and adapter.execute('GetQuantityEncoding')['quantityEncoding']:
        from backend.app.services.matching_service import pages
        pending={r['id'] for r in pages(adapter,'PageImpactIntents') if r['status']!='COMPLETED'}
        assessments=[r for r in assessments if r['transfer_id'] not in pending]
    proposals = _index(snapshot["allocation_proposals"])
    transfers = _index(snapshot["transfers"])
    supplies = _index(snapshot["supply_offers"])
    demands = _index(snapshot["demand_requests"])
    projects = _index(snapshot["projects"])
    materials = _index(snapshot["materials"])
    factors = _index(snapshot["emission_factors"])
    events_by_transfer: dict[str, list[dict[str, Any]]] = {}
    for event in snapshot["transfer_events"]:
        events_by_transfer.setdefault(event["transfer_id"], []).append(event)

    records = []
    for assessment in sorted(assessments, key=lambda row: (row["calculated_at"], row["id"])):
        transfer = (
            transfers[assessment["transfer_id"]]
            if assessment["transfer_id"] is not None
            else None
        )
        proposal = proposals[
            assessment["proposal_id"] if transfer is None else transfer["proposal_id"]
        ]
        supply = supplies[proposal["supply_offer_id"]]
        demand = demands[proposal["demand_request_id"]]
        material = materials[supply["material_id"]]
        assumptions = assessment["assumptions"]
        factor_records = assumptions.get("factor_snapshots") or [
            factors[factor_id] for factor_id in assessment["factor_ids"] if factor_id in factors
        ]
        evidence = list(supply.get("evidence_refs", []))
        if transfer is not None:
            evidence.extend(
                event["evidence_ref"]
                for event in events_by_transfer.get(transfer["id"], [])
                if event["evidence_ref"] is not None
            )
        records.append(
            {
                "assessment_id": assessment["id"],
                "basis": basis,
                "proposal_id": proposal["id"],
                "transfer_id": transfer["id"] if transfer else None,
                "source_project_id": supply["source_project_id"],
                "source_project_name": projects[supply["source_project_id"]]["name"],
                "destination_project_id": demand["destination_project_id"],
                "destination_project_name": projects[demand["destination_project_id"]]["name"],
                "material_id": material["id"],
                "material_name": material["canonical_name"],
                "quantity_assessed": assessment["quantity_assessed"],
                "moved_quantity": assumptions.get("moved_quantity"),
                "processed_quantity": assumptions.get("processed_quantity"),
                "unit": assessment["unit"],
                "calculation_status": assessment["calculation_status"],
                "components_kgco2e": {
                    "avoided_production": assessment["avoided_production_kgco2e"],
                    "additional_transport": assessment["additional_transport_kgco2e"],
                    "additional_processing": assessment["additional_processing_kgco2e"],
                    "net_avoided": assessment["net_avoided_kgco2e"],
                },
                "factor_ids": assessment["factor_ids"],
                "factors": factor_records,
                "baseline_description": assessment["baseline_description"],
                "assumptions": assumptions,
                "evidence_references": list(dict.fromkeys(evidence)),
                "missing_data": assumptions.get(
                    "missing_data",
                    [] if assessment["calculation_status"] != "INSUFFICIENT_DATA" else ["LEGACY_INCOMPLETE_BOUNDARY"],
                ),
                "revision": assumptions.get(
                    "revision",
                    {"number": 1, "previous_assessment_id": None, "legacy_seed_revision": True},
                ),
                "calculated_at": assessment["calculated_at"],
                "synthetic": True,
                "disclaimer": DISCLAIMER,
            }
        )
    if guarded and adapter.execute('GetOperationalVersion')['operationalVersion'] != read_version:
        raise ImpactConflict('IMPACT_INPUT_STALE','Impact changed while exporting. Retry the current export.')
    return [record for record in records if (
        (transfer_id is None or record["transfer_id"] == transfer_id)
        and (project_id is None or project_id in (record["source_project_id"], record["destination_project_id"]))
    )]


def export_json(basis: str, repository: ImpactRepository | None = None, project_id: str | None = None, transfer_id: str | None = None):
    return {
        "data": {
            "basis": basis,
            "records": impact_export_records(basis, repository, project_id, transfer_id),
            "aggregation": None,
            "disclaimer": DISCLAIMER,
        },
        "meta": load_baseline_metadata(),
        "error": None,
    }


def export_csv(basis: str, repository: ImpactRepository | None = None, project_id: str | None = None, transfer_id: str | None = None) -> str:
    records = impact_export_records(basis, repository, project_id, transfer_id)
    fields = [
        "assessment_id", "basis", "proposal_id", "transfer_id",
        "source_project_id", "source_project_name", "destination_project_id",
        "destination_project_name", "material_id", "material_name",
        "quantity_assessed", "moved_quantity", "processed_quantity", "unit",
        "calculation_status", "avoided_production_kgco2e",
        "additional_transport_kgco2e", "additional_processing_kgco2e",
        "net_avoided_kgco2e", "factor_ids", "factors_json",
        "baseline_description", "assumptions_json", "evidence_references_json",
        "missing_data_json", "revision_json", "calculated_at", "synthetic",
        "disclaimer",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for record in records:
        components = record["components_kgco2e"]
        writer.writerow(
            {
                **{key: record.get(key) for key in fields},
                "avoided_production_kgco2e": components["avoided_production"],
                "additional_transport_kgco2e": components["additional_transport"],
                "additional_processing_kgco2e": components["additional_processing"],
                "net_avoided_kgco2e": components["net_avoided"],
                "factor_ids": "|".join(record["factor_ids"]),
                "factors_json": json.dumps(record["factors"], ensure_ascii=False, sort_keys=True, default=json_default),
                "assumptions_json": json.dumps(record["assumptions"], ensure_ascii=False, sort_keys=True, default=json_default),
                "evidence_references_json": json.dumps(record["evidence_references"], ensure_ascii=False),
                "missing_data_json": json.dumps(record["missing_data"], ensure_ascii=False),
                "revision_json": json.dumps(record["revision"], ensure_ascii=False, sort_keys=True, default=json_default),
            }
        )
    return output.getvalue()
