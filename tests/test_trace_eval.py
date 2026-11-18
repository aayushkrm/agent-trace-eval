import json
import tempfile
import subprocess
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trace_eval as e


class TraceTests(unittest.TestCase):
    def test_order_and_arguments(self):
        c = {'id': 'x', 'task': 'task', 'calls': [{'tool': 'a', 'args': {'ok': True}}, {'tool': 'b', 'args': {}}], 'rules': {'required': ['a'], 'forbidden': ['c'], 'ordered': [['a', 'b']], 'arguments': [{'tool': 'a', 'key': 'ok', 'equals': True}]}}
        e.validate(c)
        self.assertTrue(e.grade(c)['passed'])
        c['calls'].reverse()
        self.assertFalse(e.grade(c)['passed'])

    def test_every_call_and_types(self):
        c = {'id': 'x', 'task': 'task', 'calls': [{'tool': 'a', 'args': {'ok': True}}, {'tool': 'a', 'args': {'ok': 1}}], 'rules': {'arguments': [{'tool': 'a', 'key': 'ok', 'equals': True}]}}
        self.assertFalse(e.grade(c)['passed'])

    def test_regression_and_changed_rules(self):
        old = [{'id': 'x', 'task': 'task', 'calls': [{'tool': 'a', 'args': {}}], 'rules': {'required': ['a']}}]
        new = [{'id': 'x', 'task': 'task', 'calls': [], 'rules': {'required': ['a']}}]
        self.assertEqual(e.compare(old, new)['regressions'], ['x'])
        new[0]['rules'] = {}
        with self.assertRaises(ValueError): e.compare(old, new)

    def test_rule_changes_in_already_failing_case(self):
        rules = {'required': ['a', 'b'], 'forbidden': ['c']}
        old = [{'id': 'x', 'task': 't', 'calls': [{'tool': 'a', 'args': {}}], 'rules': rules}]
        new = [{'id': 'x', 'task': 't', 'calls': [{'tool': 'b', 'args': {}}, {'tool': 'c', 'args': {}}], 'rules': rules}]
        report = e.compare(old, new)
        self.assertEqual(report['regressions'], [])
        self.assertEqual(report['improvements'], [])
        self.assertEqual(report['new_rule_failures'], 2)
        self.assertEqual(report['resolved_rule_failures'], 1)
        self.assertEqual([(r['kind'], r['index'], r['new_passed']) for r in report['rule_changes']],
                         [('required', 0, False), ('required', 1, True), ('forbidden', 0, False)])

    def test_cli_thresholds_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            old, new = Path(d) / 'old.jsonl', Path(d) / 'new.jsonl'
            rules = {'required': ['a', 'b']}
            case = {'id': 'x', 'task': 't', 'calls': [{'tool': 'a', 'args': {}}], 'rules': rules}
            old.write_text(json.dumps(case) + '\n')
            case['calls'] = []
            new.write_text(json.dumps(case) + '\n')
            cmd = [sys.executable, str(Path(e.__file__)), 'compare', str(old), str(new)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['new_rule_failures'], 1)
            self.assertEqual(subprocess.run(cmd + ['--max-new-rule-failures', '0'], capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(cmd + ['--min-pass-rate', '0.1'], capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(cmd + ['--min-pass-rate', 'nan'], capture_output=True).returncode, 2)

    def test_threshold_boundaries_and_multiple_rules(self):
        with tempfile.TemporaryDirectory() as d:
            old, new = Path(d) / 'old.jsonl', Path(d) / 'new.jsonl'
            rules = {'required': ['a'], 'ordered': [['a', 'b']],
                     'arguments': [{'tool': 'a', 'key': 'ok', 'equals': True}]}
            good = [{'tool': 'a', 'args': {'ok': True}}, {'tool': 'b', 'args': {}}]
            bad = [{'tool': 'b', 'args': {}}, {'tool': 'a', 'args': {'ok': False}}]
            before = [{'id': x, 'task': 't', 'calls': good, 'rules': rules} for x in ('x', 'y')]
            after = [dict(before[0], calls=bad), before[1]]
            old.write_text(''.join(json.dumps(c) + '\n' for c in before))
            new.write_text(''.join(json.dumps(c) + '\n' for c in after))
            cmd = [sys.executable, str(Path(e.__file__)), 'compare', str(old), str(new)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report['regressions'], ['x'])
            self.assertEqual(report['new_rule_failures'], 2)
            self.assertEqual([r['kind'] for r in report['rule_changes']], ['ordered', 'arguments'])
            self.assertEqual(subprocess.run(cmd + ['--max-regressions', '1', '--max-new-rule-failures', '2', '--min-pass-rate', '0.5'], capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(cmd + ['--max-regressions', '1', '--max-new-rule-failures', '1'], capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(cmd + ['--max-regressions', '1', '--min-pass-rate', '0.51'], capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(cmd + ['--max-regressions', '-1'], capture_output=True).returncode, 2)

    def test_task_binding(self):
        a = [{'id': 'x', 'task': 'first', 'calls': [], 'rules': {}}]
        b = [{'id': 'x', 'task': 'different', 'calls': [], 'rules': {}}]
        with self.assertRaises(ValueError): e.compare(a, b)

    def test_nonfinite_and_duplicate_keys_at_all_depths(self):
        samples = [
            '{"id":"x","task":"t","calls":[{"tool":"a","args":{"x":1e999}}],"rules":{}}',
            '{"id":"x","task":"t","calls":[],"rules":{"arguments":[{"tool":"a","key":"x","equals":-1e999}]}}',
            '{"id":"x","task":"t","calls":[{"tool":"a","args":{"x":1,"x":2}}],"rules":{}}',
            '{"id":"x","task":"t","calls":[],"rules":{"required":[],"required":[]}}',
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'run.jsonl'
            for sample in samples:
                p.write_text(sample + '\n')
                with self.subTest(sample=sample), self.assertRaises(ValueError): e.load_cases(p)

    def test_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'run.jsonl'
            p.write_text((json.dumps({'id': 'x', 'task': 'task', 'calls': [], 'rules': {}}) + '\n') * 2)
            with self.assertRaises(ValueError): e.load_cases(p)
            p.write_text('{"id":"x","task":"task","calls":[],"rules":{"unknown":[]}}\n')
            with self.assertRaises(ValueError): e.load_cases(p)


if __name__ == '__main__': unittest.main()
