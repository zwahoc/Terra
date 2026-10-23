"""Trusted, immutable prompt snapshot and enum-only document routing."""

import hashlib
from pathlib import Path

from backend.app.services.ingestion_errors import IngestionError


PROMPT_ROOT = Path(__file__).resolve().parents[1] / 'prompts'
FAMILIES = {
    'BOQ': 'boq', 'MATERIAL_REQUIREMENTS': 'material_requirements',
    'PURCHASE_ORDER': 'purchase_order', 'DELIVERY_ORDER': 'delivery_order',
    'GOODS_RECEIVED_NOTE': 'goods_received_note', 'INVENTORY': 'inventory',
    'MATERIAL_MOVEMENT': 'material_movement', 'DEMAND': 'demand',
    'SURPLUS_SALVAGE': 'surplus_salvage', 'MATERIAL_TRANSFER': 'material_transfer',
    'TECHNICAL_SUPPORT': 'technical_support', 'INVOICE': 'invoice',
    'PROGRESS_CONTEXT': 'progress_context',
}
PIPELINE_VERSION = 'terra-ingestion-2026-10-18.v8.published-record-context'


class PromptBundle:
    def __init__(self, root=PROMPT_ROOT):
        names = ['00_core.md', '10_classifier.md', '20_extractor.md', '25_semantics.md',
                 '30_batch_crosscheck.md', '35_reconciliation.md', '40_runtime.md', '45_page_groups.md', '50_repair.md', 'families/generic.md']
        names += [f'families/{name}.md' for name in FAMILIES.values()]
        try:
            self.texts = {name: (Path(root) / name).read_text(encoding='utf-8') for name in names}
            if any(not text.strip() for text in self.texts.values()):
                raise ValueError('Empty prompt module')
        except (OSError, ValueError) as exc:
            raise IngestionError('PROMPT_PACKAGE_UNAVAILABLE', 'Trusted prompt modules are missing or unreadable. No model request was sent.', 503) from exc
        self.manifest = {name: hashlib.sha256(text.encode('utf-8')).hexdigest() for name, text in self.texts.items()}
        self.identity = hashlib.sha256(str(sorted(self.manifest.items())).encode()).hexdigest()

    def compose(self, stage, modules=()):
        base = ['00_core.md']
        if stage == 'CLASSIFY_FILE':
            names = base + ['10_classifier.md']
        elif stage == 'CROSS_CHECK_BATCH':
            names = base + ['30_batch_crosscheck.md']
        elif stage == 'REPAIR_OUTPUT':
            names = base + ['50_repair.md']
        elif stage == 'RECONCILE_FILE':
            names = base + ['35_reconciliation.md']
        else:
            allowed = {f'families/{name}.md' for name in FAMILIES.values()} | {'families/generic.md'}
            if not modules or not set(modules) <= allowed:
                raise IngestionError('PROMPT_ROUTE_INVALID', 'The document route contains an untrusted module.', 500)
            names = base + ['20_extractor.md', '25_semantics.md', *modules, '40_runtime.md', '45_page_groups.md']
        return '\n\n'.join(self.texts[name].strip() for name in names)

    def route(self, classification):
        if classification is None or classification.primary_family == 'OTHER':
            return ['families/generic.md']
        selected = set(classification.applicable_families)
        names = [f'families/{name}.md' for family, name in FAMILIES.items() if family in selected]
        if classification.uncertainties:
            names.append('families/generic.md')
        return names
