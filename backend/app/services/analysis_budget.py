"""Durable usage estimates without a spending cutoff. Not a provider invoice."""

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from backend.app.services.analysis_settings import ROOT, PRICING_VERSION
from backend.app.services.ingestion_errors import IngestionError


class BudgetLedger:
    def __init__(self, settings, root: Path | None = None):
        self.settings = settings
        self.root = Path(root) if root is not None else ROOT / ".local" / "ingestion-api-budget"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "ledger.json"
        self.lock = FileLock(str(self.root / "ledger.lock"), timeout=30)

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "entries": []}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state["version"] != 1 or not isinstance(state["entries"], list):
                raise ValueError
            for entry in state["entries"]:
                amount = Decimal(entry["charged_estimate_myr"])
                if not amount.is_finite() or amount < 0:
                    raise ValueError
            return state
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            raise IngestionError("BUDGET_LEDGER_INVALID", "The local API budget ledger needs inspection; no model call was sent.", 409) from exc

    def _write(self, state):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(state, handle, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def estimate(self, spec, input_tokens, output_tokens):
        if spec.billing_mode == "FREE_TIER":
            return Decimal(0)
        return ((Decimal(input_tokens) * spec.input_usd_per_million + Decimal(output_tokens) * spec.output_usd_per_million)
                * self.settings.usd_to_myr / Decimal(1_000_000))

    def reserve(self, spec, input_bound, output_bound):
        upper = self.estimate(spec, input_bound, output_bound)
        with self.lock:
            state = self._read()
            entry_id = f"CALL-{uuid4().hex}"
            state["entries"].append({"id": entry_id, "model_id": spec.model_id,
                "provider": spec.provider, "billing_mode": spec.billing_mode,
                "pricing_version": PRICING_VERSION, "reserved_myr": str(upper),
                "charged_estimate_myr": str(upper), "status": "RESERVED_OR_UNCERTAIN"})
            self._write(state)
        return entry_id

    def settle(self, entry_id, spec, input_tokens, output_tokens):
        cost = self.estimate(spec, input_tokens, output_tokens)
        with self.lock:
            state = self._read()
            entry = next(e for e in state["entries"] if e["id"] == entry_id)
            # Never ignore an unexpected overrun of the planning bound.
            entry["charged_estimate_myr"] = str(cost)
            entry["status"] = "USAGE_REPORTED"
            entry["input_tokens"], entry["output_tokens"] = input_tokens, output_tokens
            self._write(state)
        return str(cost)

    def summary(self):
        with self.lock:
            state = self._read()
        reported, uncertain, legacy_reference = Decimal(0), Decimal(0), Decimal(0)
        for entry in state["entries"]:
            amount = Decimal(entry["charged_estimate_myr"])
            # Earlier Gemini entries used hypothetical paid rates even on this
            # free account. Preserve their bytes but separate that reference total.
            if "billing_mode" not in entry and entry["model_id"].startswith("gemini-"):
                legacy_reference += amount
            elif entry.get("billing_mode") != "FREE_TIER":
                if entry["status"] == "USAGE_REPORTED":
                    reported += amount
                else:
                    uncertain += amount
        return {"enforcement_enabled": False, "ceiling_myr": None, "remaining_estimate_myr": None,
                "spent_or_reserved_estimate_myr": str(reported + uncertain),
                "reported_usage_estimate_myr": str(reported),
                "uncertain_reservation_estimate_myr": str(uncertain),
                "legacy_gemini_paid_rate_reference_myr": str(legacy_reference),
                "calls": len(state["entries"]),
                "uncertain_calls": sum(e["status"] != "USAGE_REPORTED" for e in state["entries"]),
                "basis": "LOCAL_ESTIMATE_NOT_PROVIDER_BALANCE_OR_INVOICE"}
