"""Exact duplicate member recovery without selecting conflicting model facts."""
import json
import unittest

from backend.app.services.analysis_output import AmbiguousJSON, parse_object
from backend.app.services.analysis_providers import ProviderTurn
from tests import test_batched_repairs as batched
from tests import test_analysis as fixtures


class DuplicateJSONTests(unittest.TestCase):
    def test_identical_nested_members_are_deduplicated_with_exact_paths(self):
        events = []
        raw = '{"records":[{"inferred_fields":[],"inferred_fields":[],"raw_fields":{"a/b~c":"kept","a/b~c":"kept"}}]}'
        value, fenced = parse_object(raw, recoveries=events)
        self.assertEqual(value, {'records': [{'inferred_fields': [], 'raw_fields': {'a/b~c': 'kept'}}]})
        self.assertFalse(fenced)
        self.assertEqual({e['path'] for e in events}, {'/records/0/inferred_fields', '/records/0/raw_fields/a~1b~0c'})
        self.assertTrue(all(e['action'] == 'REMOVED_IDENTICAL_DUPLICATE_KEY' for e in events))

    def test_conflicting_members_and_nonfinite_numbers_still_fail(self):
        for raw in ('{"a":1,"a":2}', '{"a":true,"a":1}', '{"a":[true],"a":[1]}',
                    '{"a":{"x":true},"a":{"x":1}}', '{"a":null,"a":[]}',
                    '{"quantity":"1","quantity":"1.0"}', '{"a":NaN}', '{"a":Infinity}',
                    '{"a":1e999}', '{"a":1.00000000000000001,"a":1.0}'):
            with self.subTest(raw=raw):
                with self.assertRaises(AmbiguousJSON): parse_object(raw)

    def test_equal_objects_numbers_and_fences_preserve_contract(self):
        raw = '```json\n{"a":{"x":1,"y":[null]},"a":{"y":[null],"x":1},"f":1.25,"f":1.25}\n```'
        events = []
        value, fenced = parse_object(raw, recoveries=events)
        self.assertTrue(fenced)
        self.assertEqual(value, {'a': {'x': 1, 'y': [None]}, 'f': 1.25})
        self.assertIsInstance(value['f'], float)
        self.assertEqual(len(events), 2)

    def test_repeated_records_and_distinct_scopes_are_never_merged(self):
        value, _ = parse_object('{"records":[{"quantity":"4","inferred_fields":[],"inferred_fields":[]},{"quantity":"4"}]}')
        self.assertEqual(len(value['records']), 2)
        self.assertEqual([r['quantity'] for r in value['records']], ['4', '4'])

    def test_conflicting_duplicate_does_not_report_partial_success(self):
        events = []
        with self.assertRaises(AmbiguousJSON):
            parse_object('{"a":[],"a":[],"b":1,"b":2}', recoveries=events)
        self.assertEqual(events, [])

    def test_identical_duplicate_proceeds_into_batched_validation_repair(self):
        fixture = batched.BatchedRepairTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = batched.candidate(3)
        raw = json.dumps(original).replace('"quantity_basis": "MATERIAL"',
             '"inferred_fields": [], "inferred_fields": [], "quantity_basis": "MATERIAL"')
        calls = []
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']; calls.append(value)
                answer = raw if value['stage'] == 'INTERPRET_FILE' else json.dumps(batched.patches(value['allowed_paths']))
                class Session:
                    def step(inner, results=None): return ProviderTurn([], answer, fixtures.usage())
                return Session()
        result = fixture.converse(Adapter())
        self.assertEqual([t['stage'] for t in calls], ['INTERPRET_FILE', 'REPAIR_OUTPUT'])
        self.assertEqual(len(result.records), 6)
        self.assertEqual(sum(e['action'] == 'REMOVED_IDENTICAL_DUPLICATE_KEY' for e in fixture.file.recoveries), 6)
        self.assertEqual(fixture.file.response_history[0]['text'], raw)
        self.assertEqual([r.quantity for r in result.records], [r['quantity'] for r in original['records']])
