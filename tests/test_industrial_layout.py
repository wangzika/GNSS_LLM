"""目录迁移回归：不调用 GPU，验证真实样本、审阅结果和指标保持一致。"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.industrial.workflow_paths import ROOT, WorkflowPaths
from scripts.industrial.industrial_organize_data import migrate

V2 = WorkflowPaths(ROOT / 'data/industrial_v2')


def run(module, *args):
    return subprocess.run([sys.executable, '-m', 'scripts.industrial.' + module,
                           *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, check=True)


class LayoutRegression(unittest.TestCase):
    def test_original_bytes_and_all_current_links(self):
        manifest = json.loads((V2.root / 'layout.json').read_text())
        for row in manifest['files']:
            current = V2.root / row['new']
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), row['sha256'])
            self.assertFalse((V2.root / row['old']).exists())
        links = [p for p in V2.root.rglob('*') if p.is_symlink()]
        self.assertGreater(len(links), 15)
        for link in links:
            self.assertTrue(link.exists(), str(link))
            self.assertFalse(Path(link.readlink()).is_absolute(), str(link))
        registry = json.loads((ROOT / 'data/dataset_info.json').read_text())
        self.assertEqual((ROOT / 'data' / registry['industrial_v2_sft']['file_name']).resolve(),
                         V2.file('train_sft_clean.jsonl').resolve())

    def test_new_version_reproduces_original_splits(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'industrial_regression'
            run('industrial_expand_dataset', '--out-dir', out)
            layout = WorkflowPaths(out)
            for name in ('events_meta.json', 'train_meta.json', 'validation_meta.json',
                         'test_meta.json', 'validation_inputs.jsonl', 'test_inputs.jsonl',
                         'validation_labels.jsonl', 'test_labels.jsonl', 'manifest.json',
                         'source_provenance.jsonl', 'teacher_prompts_blind.txt'):
                self.assertEqual(layout.file(name).read_bytes(), V2.file(name).read_bytes(), name)
            self.assertTrue(layout.input('03_teacher', 'train_meta.json').is_file())
            self.assertFalse((out / 'train_meta.json').exists())
            self.assertEqual(len(list(out.glob('*/input'))), 6)
            self.assertEqual(len(list(out.glob('*/output'))), 6)
            dry = run('industrial_generate_teacher', '--data-dir', out, '--dry-run')
            self.assertIn('待生成 214', dry.stdout)
            repeated = subprocess.run([sys.executable, '-m',
                'scripts.industrial.industrial_expand_dataset', '--out-dir', str(out)],
                cwd=ROOT, capture_output=True)
            self.assertNotEqual(repeated.returncode, 0)

    def test_resume_and_final_review_reproduce_134_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            layout = WorkflowPaths(Path(folder) / 'review_regression')
            layout.initialize()
            for name in ('train_meta.json', 'teacher_responses.jsonl', 'teacher_raw.txt',
                         'report_audit_recomputed.jsonl', 'agent_review_decisions.jsonl'):
                shutil.copyfile(V2.file(name), layout.file(name))
            run('industrial_build_reports', '--data-dir', layout.root, '--audit-only',
                '--audit-name', 'report_audit_recomputed.jsonl', '--workers', '1')
            run('industrial_finalize_review', '--data-dir', layout.root)
            for name in ('train_sft_clean.jsonl', 'train_sft_review.jsonl',
                         'final_review_decisions.jsonl', 'audit_summary.json', 'REVIEW.md'):
                self.assertEqual(layout.file(name).read_bytes(), V2.file(name).read_bytes(), name)
            self.assertTrue(layout.input('05_finetune', 'train_sft_clean.jsonl').is_file())
            self.assertEqual(len(layout.file('train_sft_clean.jsonl').read_text().splitlines()), 134)

    def test_validation_metrics_all_protocols_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            for protocol in ('', '_reparsed', '_aligned'):
                for deterministic in (False, True):
                    suffix = '_three_classes' if deterministic else ''
                    output = Path(folder) / 'metrics.json'
                    args = ['--data-dir', V2.root, '--split', 'validation', '--predictions',
                            V2.file('validation_predictions' + protocol + '.jsonl'),
                            '--summary-json', output]
                    if deterministic:
                        args.append('--deterministic-only')
                    run('industrial_evaluate', *args)
                    expected = json.loads(V2.file('validation_metrics' + protocol + suffix + '.json').read_text())
                    actual = json.loads(output.read_text())
                    for key, value in expected.items():
                        self.assertEqual(actual[key], value, (protocol, deterministic, key))

    def test_flat_legacy_and_unknown_migration_file(self):
        old = WorkflowPaths(ROOT / 'data/industrial_v1')
        self.assertFalse(old.structured)
        self.assertEqual(old.input('03_teacher', 'train_meta.json'), old.root / 'train_meta.json')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'train_meta.json').write_text('[]')
            (root / 'unknown.bin').write_bytes(b'preserve me')
            with self.assertRaisesRegex(ValueError, '未登记'):
                migrate(root)
            self.assertTrue((root / 'train_meta.json').exists())
            self.assertEqual((root / 'unknown.bin').read_bytes(), b'preserve me')


if __name__ == '__main__':
    unittest.main()
