"""Named SQL Connect operations for isolated intake state and paginated Terra reads."""

from typing import Literal

from pydantic import ValidationError

from backend.app.schemas.ingestion import IngestionBatch
from backend.app.services.ingestion_errors import IngestionError
from terra.contract import TYPES, camel
from terra.local_adapter import AdapterError, AdapterUnavailableError, LocalDataConnect, map_entity_rows


ContextCollection = Literal["documents", "extracted_rows", "supply_offers", "demand_requests", "allocation_proposals", "transfers", "demand_commitments", "published_records", "superseded_records", "stock_heads"]
CONTEXT_COLLECTIONS = tuple(ContextCollection.__args__)


class IngestionRepository:
    def __init__(self, adapter=None):
        self.adapter = adapter if adapter is not None else LocalDataConnect()

    def execute(self, operation, variables=None, *, write=False):
        try:
            return self.adapter.execute(operation, variables, write=write)
        except AdapterUnavailableError as exc:
            raise IngestionError("INGESTION_UNAVAILABLE", "The local SQL Connect emulator is unavailable. Reload before retrying a write.", 503) from exc
        except AdapterError as exc:
            if "INGESTION_STALE_REVISION" in str(exc):
                raise IngestionError("STALE_REVISION", "The batch changed. Reload it before editing.") from exc
            raise IngestionError("INGESTION_PROVIDER_ERROR", "The SQL Connect operation failed. Reload before retrying a write.", 500) from exc

    def get(self, batch_id: str) -> IngestionBatch | None:
        result = self.execute("GetIngestionBatch", {"id": batch_id})
        try:
            row = result["ingestionBatch"]
            if row is None:
                return None
            batch = IngestionBatch.model_validate(row["payload"])
            if batch.id != batch_id or batch.revision != row["revision"]:
                raise ValueError("Stored identity mismatch")
            return batch
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise IngestionError("INGESTION_STATE_INVALID", "The stored batch is invalid.", 500) from exc

    def save(self, batch: IngestionBatch, expected_revision: int | None = None):
        values = {"id": batch.id, "revision": batch.revision,
                  "payload": batch.model_dump(mode="json"),
                  "revisionId": f"{batch.id}:{batch.revision}"}
        operation = "CreateIngestionBatch"
        if expected_revision is not None:
            operation = "UpdateIngestionBatch"
            values["expectedRevision"] = expected_revision
        self.execute(operation, values, write=True)


class TerraReadRepository(IngestionRepository):
    """No snapshot fallback. Cursor pagination is scoped to each selected collection."""

    def get_entity(self, entity: Literal["projects", "materials"], entity_id: str):
        result = self.execute("GetIntake" + TYPES[entity], {"id": entity_id})
        if entity == 'materials' and result.get('material') is None:
            registered = self.execute('GetRegisteredMaterial', {'id': entity_id})['registeredMaterial']
            if registered:
                if registered['payload'].get('id') != entity_id:
                    raise IngestionError('CONTEXT_INVALID', 'Registered material identity is invalid.', 500)
                return registered['payload']
        try:
            row = result[TYPES[entity][0].lower() + TYPES[entity][1:]]
            return map_entity_rows(entity, [row])[0] if row is not None else None
        except (KeyError, TypeError, AdapterError) as exc:
            raise IngestionError("CONTEXT_INVALID", "The provider returned invalid context.", 500) from exc

    def page(self, entity: str, *, after="", limit=100, project_id=None, query=""):
        allowed = ("projects", "materials", *CONTEXT_COLLECTIONS)
        if entity not in allowed or not 1 <= limit <= 200:
            raise IngestionError("INVALID_CONTEXT_QUERY", "Invalid collection or page size.", 422)
        variables = {"after": after, "limit": limit + 1}
        if entity in CONTEXT_COLLECTIONS:
            if not project_id:
                raise IngestionError("PROJECT_REQUIRED", "A project is required for this context query.", 422)
            variables["projectId"] = project_id
        custom = {'published_records': 'PagePublishedMaterialRecords', 'superseded_records': 'PageSupersededRecords', 'stock_heads': 'PageProjectStockHeads'}
        result = self.execute(custom.get(entity, "PageIntake" + camel(entity)[0].upper() + camel(entity)[1:]), variables)
        rows = result.get("records")
        if not isinstance(rows, list):
            raise IngestionError("CONTEXT_INVALID", "The provider returned invalid context.", 500)
        if entity == 'materials':
            registered = self.execute('PageRegisteredMaterials', variables)['records']
            rows = sorted([*rows, *registered], key=lambda row: row['id'])
        page = rows[:limit]
        try:
            key = "demandRequestId" if entity == "demand_commitments" else "id"
            ids = [row[key] for row in rows]
            if any(not isinstance(value, str) or value <= after for value in ids) or ids != sorted(set(ids)):
                raise ValueError("Invalid cursor ordering")
            if entity == "demand_commitments":
                mapped = [{"id": row["demandRequestId"], "demand_request_id": row["demandRequestId"],
                           "committed_incoming_quantity": row["committedQuantity"]} for row in page]
            elif entity in ('published_records', 'stock_heads'):
                mapped = [row['payload'] for row in page]
            elif entity == 'superseded_records':
                mapped = [{'id':row['id'],'project_id':row['projectId'],'successor_id':row['successorId']} for row in page]
            else:
                mapped = [row['payload'] if 'payload' in row else map_entity_rows(entity, [row])[0] for row in page]
            last_id = page[-1][key] if page else None
        except (KeyError, TypeError, ValueError, AdapterError) as exc:
            raise IngestionError("CONTEXT_INVALID", "The provider returned invalid context.", 500) from exc
        # Searches scan pages without hiding the continuation for filtered-out rows.
        if query:
            mapped = [row for row in mapped if query.casefold() in " ".join(
                str(row.get(field, "")) for field in ("id", "code", "name", "township", "canonical_name", "reference_code")
            ).casefold()]
        return {"records": mapped, "next_cursor": last_id if len(rows) > limit else None,
                "coverage": "PAGE", "consistency": "OBSERVED_READS"}

    def project_context(self, project_id: str):
        project = self.get_entity("projects", project_id)
        if project is None:
            raise IngestionError("PROJECT_NOT_FOUND", "The selected project does not exist.", 404)
        collections = {}
        for entity in CONTEXT_COLLECTIONS:
            records, after = [], ""
            while True:
                page = self.page(entity, project_id=project_id, after=after)
                records.extend(page["records"])
                if page["next_cursor"] is None:
                    break
                if page["next_cursor"] <= after:
                    raise IngestionError("CONTEXT_INVALID", "The provider did not advance the context cursor.", 500)
                after = page["next_cursor"]
            collections[entity] = records
        material_ids = {row["material_id"] for entity in ("supply_offers", "demand_requests") for row in collections[entity]}
        material_ids.update(row["suggested_material_id"] for row in collections["extracted_rows"] if row["suggested_material_id"])
        material_ids.update(row['material_id'] for row in collections['published_records'])
        collections["materials"] = []
        for material_id in sorted(material_ids):
            material = self.get_entity("materials", material_id)
            if material is None:
                raise IngestionError("CONTEXT_INVALID", "A referenced material is missing.", 500)
            collections["materials"].append(material)
        return {"project": project, "collections": collections,
                "coverage": "ALL_PAGES_OBSERVED", "consistency": "OBSERVED_READS",
                "stock_coverage": "NO_COMPLETE_PHYSICAL_STOCK_LEDGER",
                "synthetic_baseline": True, "baseline_as_of_date": "2026-10-12"}
