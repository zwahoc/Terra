"""Two fresh emulator runs prove durable draft recovery. Uses generic in-memory text.

Run prepare, stop the emulator, then run restore in a new emulator process.
The ignored checkpoint contains drafts only; seed verification always reads SQL Connect.
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.repositories.ingestion_repository import IngestionRepository, TerraReadRepository
from backend.app.schemas.ingestion import CaptureProjectContext, ContextPatch
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService
from backend.app.services.ingestion_storage import SourceStore
from terra.local_adapter import LocalDataConnect
from terra.seeding import seed_local, verify
from terra.validation import load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "restore"))
    args = parser.parse_args()
    if os.environ.get("GCLOUD_PROJECT") != "demo-terra-local" or not os.environ.get("DATA_CONNECT_EMULATOR_HOST"):
        parser.error("Run inside firebase emulators:exec --project demo-terra-local --only dataconnect.")
    root = Path(__file__).resolve().parents[1] / ".local" / "ingestion-recovery-proof"
    store, adapter, baseline = SourceStore(root), LocalDataConnect(), load()
    seed_local(baseline, adapter)  # Refuses to overwrite changed operational data.
    repository = IngestionRepository(adapter)
    service = IntakeService(repository, TerraReadRepository(adapter), store)
    marker = root / "proof.json"
    if args.stage == "prepare":
        batch = service.create("PRJ-001")
        service.add_files(batch.id, 1, [("hello.txt", io.BytesIO("Hello 材料".encode())),
                                      ("cells.csv", io.BytesIO(b"a,b\n1,2"))])
        service.patch_context(batch.id, ContextPatch(expected_revision=2, operator_notes="Preserve across restart"))
        batch = service.capture_project(batch.id, CaptureProjectContext(expected_revision=3, project_id="PRJ-001"))
        marker.write_text(json.dumps({"batch_id": batch.id, "revision": batch.revision}), encoding="utf-8")
        print("Prepared two originals, operator context and a SQL-confirmed revision-4 checkpoint. Stop the emulator before restore.")
    else:
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if repository.get(previous["batch_id"]) is not None:
            raise RuntimeError("A fresh emulator is required; this run still contains the batch.")
        try:
            service.get(previous["batch_id"])
        except IngestionError as exc:
            if exc.code != "DRAFT_RESTORE_REQUIRED":
                raise
        else:
            raise RuntimeError("Draft recovery must require explicit restore.")
        batch = service.restore(previous["batch_id"])
        assert batch.revision == previous["revision"] + 1
        assert batch.restored_from_revision == previous["revision"]
        assert batch.context.operator_notes == "Preserve across restart"
        assert batch.context.refresh_required and not batch.context.project_observations
        assert len(batch.submissions) == 2
        _, original = service.source(batch.id, batch.submissions[0].id)
        assert original.read_bytes() == "Hello 材料".encode()
        service.capture_project(batch.id, CaptureProjectContext(expected_revision=batch.revision, project_id="PRJ-001"))
        assert service.get(batch.id).context.project_observations
        print("Restored after a fresh emulator start: files/input retained, old observations invalidated, current context re-read through REST.")
    verify(adapter, baseline)
    print("All operational seed entities and runtime baseline counters are unchanged.")


if __name__ == "__main__":
    main()
