"""Server-only provider configuration. Secret values never enter HTTP DTOs."""

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr

from backend.app.services.ingestion_errors import IngestionError


ROOT = Path(__file__).resolve().parents[3]
PRICING_VERSION = "2026-10-16-account-mode-tracking-only"


@dataclass(frozen=True)
class ModelSpec:
    slot: str
    model_id: str
    provider: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    key: SecretStr = field(repr=False)
    billing_mode: str = "PAID"


@dataclass(frozen=True)
class AnalysisSettings:
    enabled: bool
    models: tuple[ModelSpec, ...]
    usd_to_myr: Decimal = Decimal("5")
    max_output_tokens: int = 32768
    # Provider ceiling, not a smaller Terra token budget. Omitting max_tokens
    # would restore DeepSeek's smaller default output allowance.
    deepseek_max_output_tokens: int = 393216
    timeout_seconds: int = 180
    gemini_min_interval_seconds: float = 15

    @classmethod
    def load(cls):
        # No interpolation of secrets into other variables; process environment wins.
        values = {**dotenv_values(ROOT / ".env", interpolate=False), **os.environ}
        try:
            conversion = Decimal(values.get("TERRA_LLM_USD_TO_MYR", "5"))
            interval = float(values.get("TERRA_GEMINI_MIN_INTERVAL_SECONDS", "15"))
            gemini_billing_mode = str(values.get("TERRA_GEMINI_BILLING_MODE", "FREE_TIER")).upper()
            if not conversion.is_finite() or conversion < 5 or not 0 <= interval <= 300 or gemini_billing_mode not in ("FREE_TIER", "PAID"):
                raise ValueError
            return cls(
                enabled=str(values.get("TERRA_LLM_ENABLED", "false")).lower() == "true",
                models=(
                    ModelSpec("gemini_flash", "gemini-3.8-flash", "gemini", Decimal("1.50"), Decimal("7.50"), SecretStr(values.get("GEMINI_API_KEY") or ""), gemini_billing_mode),
                    ModelSpec("gemini_flash_lite", "gemini-3.5-flash-lite", "gemini", Decimal("0.30"), Decimal("2.50"), SecretStr(values.get("GEMINI_API_KEY") or ""), gemini_billing_mode),
                    ModelSpec("deepseek_flash", "deepseek-flash", "deepseek", Decimal("0.30"), Decimal("1.20"), SecretStr(values.get("DEEPSEEK_API_KEY") or "")),
                ), usd_to_myr=conversion, gemini_min_interval_seconds=interval,
            )
        except (ValueError, ArithmeticError, TypeError) as exc:
            raise IngestionError("MODEL_CONFIGURATION_INVALID", "Use FREE_TIER or PAID Gemini billing mode, a planning USD/MYR conversion of at least 5, and a Gemini interval from 0 to 300 seconds.", 503) from exc

    def public(self):
        return {"enabled": self.enabled, "usage_tracking_only": True,
                "usd_to_myr_planning_assumption": str(self.usd_to_myr),
                "pricing_version": PRICING_VERSION,
                "cost_basis": "CONFIGURED_ACCOUNT_MODE_ESTIMATE_NOT_INVOICE",
                "max_steps": None, "max_tool_calls": None,
                "repeated_tool_block_on_attempt": 3,
                "max_output_tokens": self.max_output_tokens,
                "deepseek_max_output_tokens": self.deepseek_max_output_tokens,
                "deepseek_reasoning_effort": "HIGH",
                "gemini_min_interval_seconds": self.gemini_min_interval_seconds,
                "models": [{"slot": model.slot, "model_id": model.model_id,
                            "provider": model.provider, "billing_mode": model.billing_mode,
                            "key_configured": bool(model.key.get_secret_value())}
                           for model in self.models]}
