"""Orchestrate read-only transfer queries and baseline response metadata."""

import json
from datetime import date
from pathlib import Path
from typing import Any

from backend.app.repositories.transfer_repository import (
    TransferRepository,
    TransferRepositoryError,
    TransferRepositoryUnavailable,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SEED_FILE = PROJECT_ROOT / "data" / "terra_seed.json"
_REQUIRED_METADATA_FIELDS = ("version", "synthetic", "as_of_date")


class TransferReadError(Exception):
    """A safe, API-facing transfer read failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TransferReadUnavailable(TransferReadError):
    """The configured local transfer data source is unavailable."""


class TransferNotFound(TransferReadError):
    """No transfer matched the requested stable ID."""

    def __init__(self, transfer_id: str) -> None:
        super().__init__("TRANSFER_NOT_FOUND", "The requested transfer was not found.")
        self.transfer_id = transfer_id


class RelatedRecordNotFound(TransferReadError):
    def __init__(self, code: str, message: str, record_id: str) -> None:
        super().__init__(code, message)
        self.record_id = record_id


def _invalid_metadata(message: str) -> TransferReadError:
    return TransferReadError("BASELINE_METADATA_INVALID", message)


def load_baseline_metadata() -> dict[str, Any]:
    """Read only immutable dataset metadata; transfer rows come from SQL Connect."""

    try:
        with SEED_FILE.open("r", encoding="utf-8") as file:
            seed = json.load(file)
    except FileNotFoundError as exc:
        raise TransferReadError(
            "BASELINE_METADATA_NOT_FOUND", "Baseline dataset metadata is unavailable."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _invalid_metadata("Baseline dataset metadata is not valid JSON.") from exc
    except OSError as exc:
        raise TransferReadError(
            "BASELINE_METADATA_UNAVAILABLE",
            "Baseline dataset metadata could not be read.",
        ) from exc

    if not isinstance(seed, dict) or not isinstance(seed.get("metadata"), dict):
        raise _invalid_metadata("Baseline dataset metadata must be a JSON object.")

    metadata = seed["metadata"]
    if any(field not in metadata for field in _REQUIRED_METADATA_FIELDS):
        raise _invalid_metadata("Baseline dataset metadata is missing required fields.")
    if not isinstance(metadata["version"], str) or not metadata["version"].strip():
        raise _invalid_metadata("Baseline dataset version must be a non-empty string.")
    if type(metadata["synthetic"]) is not bool:
        raise _invalid_metadata("Baseline dataset synthetic must be a boolean.")
    if not isinstance(metadata["as_of_date"], str):
        raise _invalid_metadata("Baseline dataset as_of_date must be an ISO 8601 date.")
    try:
        date.fromisoformat(metadata["as_of_date"])
    except ValueError as exc:
        raise _invalid_metadata(
            "Baseline dataset as_of_date must be an ISO 8601 date."
        ) from exc

    return {
        "dataset_version": metadata["version"],
        "synthetic": metadata["synthetic"],
        "as_of_date": metadata["as_of_date"],
    }


def _repository() -> TransferRepository:
    try:
        return TransferRepository()
    except TransferRepositoryError as exc:
        raise TransferReadError(
            "TRANSFER_DATA_ERROR", "Transfer data could not be read."
        ) from exc


def _read_records(repository: TransferRepository) -> list[dict[str, Any]]:
    try:
        return repository.list()
    except TransferRepositoryUnavailable as exc:
        raise TransferReadUnavailable(
            "TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.",
        ) from exc
    except TransferRepositoryError as exc:
        raise TransferReadError(
            "TRANSFER_DATA_ERROR", "Transfer data could not be read."
        ) from exc


def _read_record(
    repository: TransferRepository, transfer_id: str
) -> dict[str, Any] | None:
    try:
        return repository.get(transfer_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferReadUnavailable(
            "TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.",
        ) from exc
    except TransferRepositoryError as exc:
        raise TransferReadError(
            "TRANSFER_DATA_ERROR", "Transfer data could not be read."
        ) from exc


def list_transfers(
    repository: TransferRepository | None = None,
) -> dict[str, Any]:
    """Return live emulator transfers with immutable baseline metadata."""

    records = _read_records(repository or _repository())
    return {"data": records, "meta": load_baseline_metadata(), "error": None}


def get_transfer(
    transfer_id: str, repository: TransferRepository | None = None
) -> dict[str, Any]:
    """Return one transfer via the bounded named list operation."""

    transfer = _read_record(repository or _repository(), transfer_id)
    if transfer is None:
        raise TransferNotFound(transfer_id)
    return {"data": transfer, "meta": load_baseline_metadata(), "error": None}


def get_transfer_events(transfer_id: str, repository: TransferRepository | None = None):
    repository = repository or _repository()
    if _read_record(repository, transfer_id) is None:
        raise TransferNotFound(transfer_id)
    try:
        records = repository.list_events(transfer_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferReadUnavailable("TRANSFER_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable.") from exc
    except TransferRepositoryError as exc:
        raise TransferReadError("TRANSFER_DATA_ERROR", "Transfer events could not be read.") from exc
    return {"data": records, "meta": load_baseline_metadata(), "error": None}


def get_supply_offer(offer_id: str, repository: TransferRepository | None = None):
    repository = repository or _repository()
    try:
        record = repository.get_supply_offer(offer_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferReadUnavailable("TRANSFER_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable.") from exc
    except TransferRepositoryError as exc:
        raise TransferReadError("TRANSFER_DATA_ERROR", "Supply data could not be read.") from exc
    if record is None:
        raise RelatedRecordNotFound("SUPPLY_OFFER_NOT_FOUND", "The requested supply offer was not found.", offer_id)
    return {"data": record, "meta": load_baseline_metadata(), "error": None}


def get_demand_request(demand_id: str, repository: TransferRepository | None = None):
    repository = repository or _repository()
    try:
        record = repository.get_demand_request(demand_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferReadUnavailable("TRANSFER_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable.") from exc
    except TransferRepositoryError as exc:
        raise TransferReadError("TRANSFER_DATA_ERROR", "Demand data could not be read.") from exc
    if record is None:
        raise RelatedRecordNotFound("DEMAND_REQUEST_NOT_FOUND", "The requested demand request was not found.", demand_id)
    return {"data": record, "meta": load_baseline_metadata(), "error": None}
