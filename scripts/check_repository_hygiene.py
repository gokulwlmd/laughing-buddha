"""Offline source hygiene checks. Prints paths/rules, never matched secret values.

Checks the tracked working tree; --include-untracked also checks new, nonignored
files. This is a guard against common mistakes, not a comprehensive secret/PII
scanner. Git history, ignored local files and image contents are not scanned.
"""
import argparse
import fnmatch
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SECRET_RULES = {
    'private key material': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    'AWS access key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'Stripe private key': re.compile(rb'\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{24,}\b'),
    'GitHub credential': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'credential-bearing database URL': re.compile(rb'(?i)\b(?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?)://[^\s/:]+:[^\s/@]+@'),
}


def path_problem(path):
    p = PurePosixPath(path)
    parts, name = p.parts, p.name.lower()
    if parts[0] in ('outputs', 'prototypes', '.local-archive'):
        return 'local/generated artifact directory'
    if any(part in ('node_modules', 'vendor', '__pycache__', '.venv', '.state', 'playwright-report', 'test-results') for part in parts):
        return 'dependency, cache or runtime directory'
    if path.startswith('tools/stripe-v2-checkout/qa/results/'):
        return 'generated QA results'
    if name.endswith(('.orig', '.rej', '~', '.har', '.pyc', '.zip', '.tar.gz')):
        return 'backup, capture or generated archive'
    if re.search(r'\.(?:sqlite3?|db)(?:-.*)?$', name):
        return 'runtime database'
    if name in ('admin-setup-token', 'access-token') or name.endswith(('.key', '.pem', '.p12', '.pfx')):
        return 'private runtime credential file'
    if (name == '.env' or name.startswith('.env.') or name.endswith('.env')) and not name.endswith('.example'):
        return 'private environment file'
    return None


def content_problems(data):
    return [name for name, expression in SECRET_RULES.items() if expression.search(data)]


def docker_included(path, patterns):
    """Evaluate this repository's flat allowlist for literal COPY inputs."""
    included = True
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern or pattern.startswith('#'):
            continue
        allow = pattern.startswith('!')
        pattern = pattern.lstrip('!').strip('/')
        if fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern + '/'):
            included = allow
    return included


def container_problems(root):
    app = root / 'tools/stripe-v2-checkout'
    if not (app / 'Dockerfile').exists():
        return []
    patterns = (app / '.dockerignore').read_text().splitlines()
    issues = []
    for line in (app / 'Dockerfile').read_text().replace('\\\n', ' ').splitlines():
        if not line.upper().startswith('COPY '):
            continue
        tokens = shlex.split(line)[1:]
        if any(token.startswith('--from=') for token in tokens):
            continue
        sources = [token for token in tokens if not token.startswith('--')][:-1]
        for source in sources:
            if not (app / source).exists():
                issues.append((str((app / source).relative_to(root)), 'Docker COPY source missing'))
            elif not docker_included(source, patterns):
                issues.append((str((app / source).relative_to(root)), 'Docker COPY source excluded by .dockerignore'))
    return issues


def check(root, paths):
    issues = []
    for path in paths:
        file = root / path
        if not file.exists():  # A working-tree deletion is a legitimate cleanup.
            continue
        if file.is_symlink():
            issues.append((path, 'review symlinks before distributing source'))
            continue
        problem = path_problem(path)
        if problem:
            issues.append((path, problem))
        if file.is_file():
            data = file.read_bytes()
            issues.extend((path, rule) for rule in content_problems(data))
            if path.startswith('.github/workflows/'):
                for action in re.findall(rb'\buses:\s*([^\s#]+)', data):
                    if not action.startswith(b'./') and not re.fullmatch(rb'[^@]+@[0-9a-f]{40}', action):
                        issues.append((path, 'workflow action must use a full commit SHA'))
    return issues + container_problems(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-untracked', action='store_true')
    args = parser.parse_args()
    command = ['git', 'ls-files', '-z', '--cached']
    if args.include_untracked:
        command += ['--others', '--exclude-standard']
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    paths = sorted(set(result.stdout.decode().split('\0')) - {''})
    issues = check(ROOT, paths)
    for path, rule in issues:
        print(f'{path}: {rule}')
    if issues:
        raise SystemExit(f'Repository hygiene failed: {len(issues)} finding(s). No secret values printed.')
    print(f'Repository hygiene passed ({len(paths)} paths; current files only, not a history/PII audit).')


if __name__ == '__main__':
    main()
