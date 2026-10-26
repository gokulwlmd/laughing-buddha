import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('hygiene', Path(__file__).parents[1] / 'check_repository_hygiene.py')
hygiene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hygiene)


class RepositoryHygieneTests(unittest.TestCase):
    def test_private_and_generated_paths_are_blocked(self):
        for path in ['app/.env', 'app/.env.production', 'backend.env', 'app/data.sqlite3-wal',
                     'x/member-identity.key', 'app.py.orig', 'outputs/review.xlsx',
                     'prototypes/site/index.html', 'x/node_modules/lib.js', 'capture.har']:
            with self.subTest(path=path):
                self.assertIsNotNone(hygiene.path_problem(path))

    def test_examples_and_runtime_source_remain_allowed(self):
        for path in ['.env.example', 'deploy/backend.env.example', 'app/mysql_schema.json',
                     'app/demo/session_api.py', 'app/patient_demo/provider.py', 'docs/README.md']:
            with self.subTest(path=path):
                self.assertIsNone(hygiene.path_problem(path))

    def test_high_confidence_credential_patterns(self):
        values = [b'sk_live_' + b'x' * 24, b'AKIA' + b'A' * 16,
                  b'ghp_' + b'x' * 36, b'-----BEGIN ' + b'PRIVATE KEY-----',
                  b'mysql://' + b'person:credential@host/db']
        for value in values:
            self.assertTrue(hygiene.content_problems(value))
        self.assertFalse(hygiene.content_problems(b'MYSQL_PASSWORD=\nSTICKY_API_PASSWORD=\n'))

    def test_container_missing_or_ignored_file_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / 'tools/stripe-v2-checkout'
            app.mkdir(parents=True)
            (app / 'Dockerfile').write_text('COPY --chown=1:1 app.py database.py missing.py ./\n')
            (app / 'app.py').write_text('')
            (app / 'database.py').write_text('')
            (app / '.dockerignore').write_text('*\n!app.py\n')
            issues = hygiene.container_problems(root)
            self.assertEqual(len(issues), 2)
            self.assertTrue(any('excluded' in rule for _, rule in issues))
            self.assertTrue(any('missing' in rule for _, rule in issues))
            (app / '.dockerignore').write_text('*\n!app.py\n!database.py\n!missing.py\n')
            (app / 'missing.py').write_text('')
            self.assertEqual(hygiene.container_problems(root), [])

    def test_unpinned_actions_fail_and_deleted_artifacts_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / '.github/workflows/test.yml'
            workflow.parent.mkdir(parents=True)
            workflow.write_text('steps:\n - uses: actions/checkout@v4\n')
            paths = ['.github/workflows/test.yml', 'outputs/removed.xlsx']
            self.assertEqual(len(hygiene.check(root, paths)), 1)
            workflow.write_text('steps:\n - uses: actions/checkout@' + 'a' * 40 + '\n')
            self.assertEqual(hygiene.check(root, paths), [])


if __name__ == '__main__':
    unittest.main()
