"""Complete, unranked catalogue search; no model requests or operational writes."""

import copy
import unittest

from backend.app.schemas.analysis import AnalysisRun
from backend.app.services.analysis_providers import ToolCall
from backend.app.services.analysis_tools import FrozenTerraReads, ToolExecutor
from backend.app.services.ingestion_errors import IngestionError


class CatalogueReads:
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda row: row['id'])
        self.calls = []

    def page(self, entity, *, after='', limit=100, query=''):
        assert entity == 'materials'
        self.calls.append((after, limit, query))
        remaining = [copy.deepcopy(row) for row in self.rows if row['id'] > after]
        page = remaining[:limit]
        if query:
            page = [row for row in page if query.casefold() in row['canonical_name'].casefold()]
        return {'records': page, 'next_cursor': remaining[limit - 1]['id'] if len(remaining) > limit else None}

    def get_entity(self, entity, entity_id):
        return next((copy.deepcopy(row) for row in self.rows if row['id'] == entity_id), None)


def material(number, name, **values):
    return {'id': f'MAT-{number:04}', 'canonical_name': name, 'reference_code': None,
            'category': 'PAVING', 'standard_unit': 'pcs', 'specifications': {}, **values}


class MaterialSearchTests(unittest.TestCase):
    def executor(self, rows):
        self.reads = CatalogueReads(rows)
        self.run = AnalysisRun(id='AIR-search', model_slot='deepseek_flash', model_id='deepseek-flash', files=[])
        return ToolExecutor(self.run, FrozenTerraReads(self.reads), lambda _: None)

    def search(self, executor, **query):
        value = executor.execute(ToolCall('bulk', 'search_materials_bulk', {'queries': [
            {'query_id': 'line-1', **query}]}))['result']
        self.assertIn('results', value, value)
        return value['results'][0]

    def test_alternative_names_and_all_words_search_specs_without_ranking(self):
        executor = self.executor([
            material(1, 'Concrete paving block', specifications={'thickness_mm': 60, 'colour': 'grey'}),
            material(2, 'Interlocking paver', specifications={'thickness_mm': 80}),
            material(3, 'Brick', specifications={'application': 'paving'}),
        ])
        result = self.search(executor, terms=['paver', 'paving'], match_mode='ANY')
        self.assertEqual([r['id'] for r in result['records']], ['MAT-0001', 'MAT-0002', 'MAT-0003'])
        selected = self.search(executor, query='grey concrete 60', match_mode='ALL')
        self.assertEqual([r['id'] for r in selected['records']], ['MAT-0001'])
        self.assertEqual(selected['records'][0]['specifications']['thickness_mm'], 60)
        self.assertEqual(result['search']['ordering'], 'ID_ASCENDING_NO_RELEVANCE_RANKING')
        self.assertTrue(result['search']['complete'])
        self.assertNotIn('score', result['records'][0])

    def test_later_matches_return_without_empty_filtered_pages_or_hidden_cap(self):
        rows = [material(i, 'Other item', category='GENERAL') for i in range(1, 1106)]
        rows[1004]['canonical_name'] = 'Paving alpha'
        rows[1104]['canonical_name'] = 'Paving beta'
        executor = self.executor(rows)
        first = self.search(executor, terms=['paving'], limit=1)
        self.assertEqual([r['id'] for r in first['records']], ['MAT-1005'])
        self.assertEqual(first['next_cursor'], 'MAT-1005')
        self.assertFalse(first['search']['complete'])
        second = self.search(executor, terms=['paving'], limit=1, after=first['next_cursor'])
        self.assertEqual([r['id'] for r in second['records']], ['MAT-1105'])
        self.assertIsNone(second['next_cursor'])
        self.assertTrue(second['search']['complete'])
        self.assertEqual(len(self.run.proposals), 0)

    def test_complete_empty_result_and_bulk_share_raw_pages(self):
        executor = self.executor([material(i, 'Tile') for i in range(1, 306)])
        result = executor.execute(ToolCall('bulk', 'search_materials_bulk', {'queries': [
            {'query_id': 'one', 'terms': ['paver']}, {'query_id': 'two', 'terms': ['drain']}
        ]}))['result']
        for entry in result['results']:
            self.assertEqual(entry['records'], [])
            self.assertTrue(entry['search']['complete'])
            self.assertEqual(entry['search']['scanned_records'], 305)
        self.assertEqual(len(self.reads.calls), 4)
        self.assertEqual(executor.progress_count, 1, 'Changed query text alone is not new evidence')

    def test_field_scope_literal_phrase_and_casefold_are_explicit(self):
        executor = self.executor([material(1, 'Concrete paving', reference_code='PVR-60',
            specifications={'description': 'PRECAST   block', 'thickness_mm': 60})])
        result = self.search(executor, terms=['precast block'], search_fields=['specifications'])
        self.assertEqual(len(result['records']), 1)
        no_name_match = self.search(executor, terms=['concrete'], search_fields=['reference_code'])
        self.assertEqual(no_name_match['records'], [])
        self.assertEqual(no_name_match['search']['fields'], ['reference_code'])

    def test_equivalent_flexible_queries_share_repetition_counter(self):
        executor = self.executor([material(1, 'Concrete paving')])
        self.search(executor, terms=['PAVING', 'concrete'], match_mode='ALL')
        self.search(executor, terms=['concrete', 'paving'], match_mode='ALL')
        third = self.search(executor, terms=[' concrete ', 'paving'], match_mode='ALL')
        self.assertEqual(third['status'], 'REPEATED_REQUEST_BLOCKED')

    def test_invalid_queries_do_not_read_or_create_proposals(self):
        executor = self.executor([])
        for query in ({'query': 'paving', 'terms': ['block']}, {'terms': ['   ']},
                      {'terms': ['paving'], 'search_fields': []},
                      {'terms': ['paving'], 'search_fields': ['price']}):
            result = executor.execute(ToolCall('bad', 'search_materials_bulk', {'queries': [
                {'query_id': 'bad', **query}]}))['result']
            self.assertEqual(result['error']['code'], 'TOOL_ARGUMENTS_INVALID')
        self.assertEqual(self.reads.calls, [])
        self.assertEqual(self.run.proposals, [])

    def test_nonadvancing_provider_cursor_is_an_error_not_absence(self):
        executor = self.executor([])
        self.reads.page = lambda *args, **kwargs: {'records': [], 'next_cursor': kwargs['after']}
        with self.assertRaises(IngestionError) as caught:
            self.search(executor, terms=['paving'])
        self.assertEqual(caught.exception.code, 'CONTEXT_INVALID')

    def test_same_name_different_thickness_does_not_merge_proposals(self):
        executor = self.executor([])
        references = []
        for thickness in ('60', '80'):
            result = executor.execute(ToolCall(thickness, 'propose_material', {
                'canonical_name': 'Concrete paving block', 'standard_unit': 'pcs',
                'specifications': {'thickness_mm': thickness}}))['result']
            references.append(result['proposal']['id'])
        self.assertEqual(len(set(references)), 2)
        self.assertTrue(all(ref.startswith('DRAFT-MATERIAL-') for ref in references))
        self.assertEqual(self.reads.rows, [])

    def test_prompt_requires_investigation_and_specific_evidence_gaps(self):
        from backend.app.services.analysis_prompts import PromptBundle
        prompt = PromptBundle().compose('INTERPRET_FILE', ['families/boq.md'])
        for requirement in ('alternative terms', 'search.complete=true', 'no length/width',
                            'propose_material', 'without relevance ranking',
                            'material_ref.kind=PROPOSED', 'no-operational-write'):
            if requirement == 'no-operational-write':
                self.assertIn('do not create approved catalogue records', prompt)
            else:
                self.assertIn(requirement, prompt)
        classifier = PromptBundle().compose('CLASSIFY_FILE')
        self.assertNotIn('Material-resolution procedure', classifier)

    def test_framework_independent_pipeline_accepts_each_provisional_outcome(self):
        # Scripted decisions verify transport/reference contracts, not LLM accuracy.
        import json
        from tests import test_analysis as fixtures
        from backend.app.services.analysis_providers import ProviderTurn
        fixture = fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        catalogue = CatalogueReads([material(1, 'Concrete paving block', specifications={
            'length_mm': 200, 'width_mm': 100, 'thickness_mm': 60, 'colour': 'grey'})])

        class Reads(fixtures.ModelReads):
            def page(self, entity, **kwargs):
                return catalogue.page(entity, **kwargs) if entity == 'materials' else super().page(entity, **kwargs)

            def get_entity(self, entity, entity_id):
                return catalogue.get_entity(entity, entity_id) if entity == 'materials' else super().get_entity(entity, entity_id)

        fixture.intake.reads = Reads()
        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)['task']
                if task['stage'] != 'INTERPRET_FILE':
                    return super().session(system, instruction, attachments, tools, output_schema)
                class Session:
                    def step(self, results=None):
                        if results is None:
                            return ProviderTurn([
                                ToolCall('search', 'search_materials_bulk', {'queries': [
                                    {'query_id': 'paver', 'terms': ['paver', 'paving'], 'match_mode': 'ANY'}]}),
                                ToolCall('variant', 'propose_material', {'canonical_name': 'Concrete block 80 mm',
                                    'specifications': {'thickness_mm': '80'}, 'standard_unit': 'pcs'}),
                                ToolCall('new', 'propose_material', {'canonical_name': 'Non-woven geotextile',
                                    'specifications': {'weight_gsm': '200'}, 'standard_unit': 'm2'}),
                            ], '', fixtures.usage())
                        existing = results[0]['result']['results'][0]['records'][0]['id']
                        variant, new = (entry['result']['proposal']['id'] for entry in results[1:])
                        outcomes = [
                            ('Interlocking paver, 200 x 100 x 60 mm grey', {'kind': 'EXISTING', 'id': existing}, []),
                            ('Concrete block 80 mm', {'kind': 'PROPOSED', 'id': variant}, []),
                            ('Paver 60 mm', None, ['Missing length/width; existing 200 x 100 mm identity unconfirmed']),
                            ('Non-woven geotextile 200 gsm', {'kind': 'PROPOSED', 'id': new}, []),
                        ]
                        return ProviderTurn([], json.dumps({'extraction_version':'MATERIAL_V2','document_type': 'BOQ', 'summary': 'Scripted outcomes',
                            'records': [{'raw_description': description, 'material_ref': ref, 'issues': issues,
                                         'record_kind': 'PLANNED_REQUIREMENT'} for description, ref, issues in outcomes]}), fixtures.usage())
                return Session()
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        result = fixture.start()
        for run in result['runs']:
            self.assertEqual(run['status'], 'SUCCEEDED', run['files'][0]['error'])
            rows = run['files'][0]['draft']['records']
            self.assertEqual(rows[0]['material_ref']['id'], 'MAT-0001')
            self.assertEqual(rows[1]['material_ref']['kind'], 'PROPOSED')
            self.assertIsNone(rows[2]['material_ref'])
            self.assertIn('length/width', rows[2]['issues'][0])
            self.assertEqual(rows[3]['material_ref']['kind'], 'PROPOSED')
            self.assertEqual(len(run['proposals']), 2)
        self.assertEqual(catalogue.rows[0]['specifications']['thickness_mm'], 60)


if __name__ == '__main__':
    unittest.main()
