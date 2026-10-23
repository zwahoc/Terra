"""Explicit live model probe, using a generic diagnostic by default or owner-supplied files.

Run only inside a fresh demo emulator. Credentials stay in .env; output omits their values.
This is not a construction-document generator or a publication command.
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.repositories.ingestion_repository import IngestionRepository, TerraReadRepository
from backend.app.schemas.analysis import AnalyseRequest
from backend.app.services.analysis_service import ComparisonService
from backend.app.services.analysis_settings import AnalysisSettings, ROOT
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService
from terra.local_adapter import LocalDataConnect
from terra.seeding import seed_local, verify
from terra.validation import load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly send model requests with local usage tracking and no spending cutoff")
    parser.add_argument("--file", type=Path, action="append", default=[], help="Existing owner-provided input, repeatable")
    args = parser.parse_args()
    if not args.live:
        parser.error("Add --live to acknowledge outbound provider calls. Automated tests never use this command.")
    if os.environ.get("GCLOUD_PROJECT") != "demo-terra-local" or not os.environ.get("DATA_CONNECT_EMULATOR_HOST"):
        parser.error("Use firebase emulators:exec --only dataconnect --project demo-terra-local.")
    config = AnalysisSettings.load()
    if not config.enabled or not all(model.key.get_secret_value() for model in config.models):
        parser.error("Set both keys and TERRA_LLM_ENABLED=true in local .env first. Key values must stay local.")
    adapter, baseline = LocalDataConnect(), load()
    seed_local(baseline, adapter)
    intake = IntakeService(IngestionRepository(adapter), TerraReadRepository(adapter))
    batch = intake.create()
    files = [(path.name, io.BytesIO(path.read_bytes())) for path in args.file]
    if not files:
        files = [("connectivity.txt", io.BytesIO(b"Generic API connectivity test. Project reference: PRJ-001. No material quantities are provided."))]
    intake.add_files(batch.id, 1, files)
    service = ComparisonService(intake, config)
    comparison = service.start(batch.id, AnalyseRequest(expected_revision=2, idempotency_key="live-probe", mode="COMPARE"))
    previous, started = None, time.monotonic()
    while True:
        comparison = service.get(batch.id, comparison["id"])
        statuses = [(r["model_slot"], r["status"]) for r in comparison["runs"]]
        if statuses != previous:
            print(json.dumps({"progress": statuses}), flush=True)
            previous = statuses
        if all(status not in ("PENDING", "RUNNING") for _, status in statuses):
            break
        if time.monotonic() - started > 600:
            print("Probe polling timed out. Existing workers are not retried; inspect the stored comparison and budget before any new action.", flush=True)
            break
        time.sleep(0.25)
    report = {"batch_id": batch.id, "comparison_id": comparison["id"],
              "generic_diagnostic": not bool(args.file), "budget": service.ledger.summary(),
              "runs": [{"model_id": run["model_id"], "model_slot": run["model_slot"], "status": run["status"],
                        "tool_calls": len(run["observations"]), "usage": run["usage"],
                        "files": [{"status": file["status"], "error": file["error"],
                                   "record_count": len(file["draft"]["records"]) if file["draft"] else None} for file in run["files"]],
                        "cross_check_error": run["cross_check_error"]} for run in comparison["runs"]]}
    (ROOT / ".local" / "phase2-live-proof.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    verify(adapter, baseline)
    print("Operational baseline unchanged. Results are draft-only; no model was selected automatically.")
    return 0 if all(run["status"] == "SUCCEEDED" for run in comparison["runs"]) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except IngestionError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        sys.exit(1)
