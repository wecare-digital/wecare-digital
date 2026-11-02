"""Retirement must reject publication before any AWS client call."""
import ast
from pathlib import Path
import typing
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackendRetirementTests(unittest.TestCase):
    def publisher(self, state):
        source = ROOT / 'scripts/snapstart_publish.py'
        tree = ast.parse(source.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'publish_and_move')
        calls = []
        namespace = {
            'Optional': typing.Optional,
            'ALIAS': 'live',
            'current_state': lambda *args: calls.append(args) or state,
            'environment_matches': lambda *args: True,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
        return namespace['publish_and_move'], calls

    def test_retired_functions_rejected_without_reading_or_mutating_aws(self):
        publish, calls = self.publisher(None)
        for name in ('wecare-ai-generate-response', 'wecare-meta-catalog-sync'):
            with self.assertRaisesRegex(ValueError, 'Retired function'):
                publish(object(), name, False, False)
        self.assertEqual(calls, [])

    def test_concurrent_code_change_still_blocks_publication(self):
        state = typing.NamedTuple('State', [('alias_version', str), ('alias_sha', str), ('latest_sha', str), ('alias_revision', str), ('latest_revision', str)])('1', 'old', 'other-deployer', None, None)
        publish, calls = self.publisher(state)
        self.assertEqual(publish(object(), 'wecare-contacts', False, False, expected_sha='my-release'), 'failed')
        self.assertEqual(len(calls), 1)

    def test_matching_alias_skips_without_client_mutation(self):
        state = typing.NamedTuple('State', [('alias_version', str), ('alias_sha', str), ('latest_sha', str), ('alias_revision', str), ('latest_revision', str)])('1', 'same', 'same', None, None)
        publish, _ = self.publisher(state)
        self.assertEqual(publish(object(), 'wecare-contacts', False, True), 'skipped')

    def test_current_function_dry_run_never_uses_client_mutations(self):
        state = typing.NamedTuple('State', [('alias_version', str), ('alias_sha', str), ('latest_sha', str), ('alias_revision', str), ('latest_revision', str)])('1', 'old', 'new', None, None)
        publish, _ = self.publisher(state)
        self.assertEqual(publish(object(), 'wecare-contacts', True, False, expected_sha='new'), 'skipped')


if __name__ == '__main__':
    unittest.main()
