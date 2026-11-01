"""Scan reachable history and a reviewed source snapshot; never expose secrets."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from tools.build_native import ROOT
from tools.source_policy import is_public_source

VERSION = "8.30.1"


def main():
    cache = ROOT / ".sdk/gitleaks"
    executable = cache / "gitleaks.exe"
    name = f"gitleaks_{VERSION}_windows_x64.zip"
    base = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/"
    def fetch(filename):
        with urllib.request.urlopen(base + filename, timeout=120) as response: return response.read()
    if not executable.is_file():
        checksums = fetch(f"gitleaks_{VERSION}_checksums.txt").decode()
        expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name)
        archive = fetch(name)
        if hashlib.sha256(archive).hexdigest() != expected:
            raise RuntimeError("Gitleaks archive checksum mismatch.")
        cache.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            executable.write_bytes(package.read("gitleaks.exe"))
    output = ROOT / "artifacts/privacy-checks"
    output.mkdir(parents=True, exist_ok=True)
    (ROOT / 'tmp').mkdir(exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix='public-source-', dir=ROOT / 'tmp'))
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    for name in names:
        if name and is_public_source(name):
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise RuntimeError('Refused a missing source file or filesystem link.')
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    scans = []
    for scope, command in [('history', ['git', str(ROOT), '--log-opts=--all']),
                           ('reviewed-current-source', ['dir', str(snapshot)])]:
        report = output / f'gitleaks-{scope}-redacted.json'
        result = subprocess.run([str(executable), *command, '--redact=100', '--no-banner',
            '--report-format=json', '--report-path=' + str(report)], capture_output=True, text=True)
        findings = (json.loads(report.read_text()) or []) if report.is_file() else []
        scans.append({'scope': scope, 'exit_code': result.returncode, 'findings': len(findings),
            'rule_ids': sorted({item.get('RuleID', 'unknown') for item in findings})})
    summary = {'scanner': 'gitleaks', 'version': VERSION, 'scans': scans,
        'findings': sum(item['findings'] for item in scans)}
    (output / "secret-scan-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    raise SystemExit(1 if any(item['exit_code'] for item in scans) else 0)


if __name__ == "__main__":
    main()
