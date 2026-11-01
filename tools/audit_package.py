"""Audit a portable staging tree without printing private matching values."""
import argparse
import base64
import csv
import hashlib
import json
import os
from pathlib import Path
import re

BLOCKED = {".git", ".promptcad", ".codex", ".aws", ".azure", "projects", "conversations", "sessions", "__pycache__"}
PRIVATE = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{64,}")


def wheel_hashes(root):
    site = root / 'python/Lib/site-packages'
    hashes = {}
    for record in site.glob('*.dist-info/RECORD'):
        with record.open(encoding='utf-8', newline='') as stream:
            for row in csv.reader(stream):
                if len(row) < 2 or not row[1].startswith('sha256='):
                    continue
                path = (site / row[0]).resolve()
                if path.is_relative_to(site):
                    hashes[path] = row[1].split('=', 1)[1]
    return hashes


def audit(root):
    root = Path(root).resolve()
    findings = []
    count = 0
    public_build_paths = 0
    recorded_hashes = wheel_hashes(root)
    user = Path.home().name
    private_paths = [(drive + ":/Users/" + user).lower() for drive in ("C", "D")]
    checkout = str(Path(__file__).resolve().parents[1]).replace("\\", "/").lower()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_symlink():
            findings.append("filesystem link")
            continue
        if not path.is_file():
            continue
        count += 1
        if any(part.lower() in BLOCKED for part in relative.parts) or path.suffix.lower() in (".dpapi", ".pdb", ".pyc") or path.name.lower() in ("auth.json", "credentials.json", ".env", "direct_url.json"):
            findings.append("runtime/user/development data")
        data = path.read_bytes()
        if PRIVATE.search(data):
            findings.append("private key material")
        text = data.decode("utf-8", errors="ignore").replace("\\", "/").lower()
        wide = data.decode("utf-16-le", errors="ignore").replace("\\", "/").lower()
        if checkout in text or checkout in wide:
            findings.append("host-specific path")
        elif any(value in text or value in wide for value in private_paths):
            # Public Windows wheels embed GitHub's standard build-account paths.
            # Allow only byte-identical wheel files, never application/generated files.
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            if user.lower() == 'runneradmin' and recorded_hashes.get(path.resolve()) == digest:
                public_build_paths += 1
            else:
                findings.append("host-specific path")
    if findings:
        categories = {name: findings.count(name) for name in set(findings)}
        raise RuntimeError("Portable privacy audit failed (values withheld): " + json.dumps(categories))
    return {"passed": True, "files": count, "private_matches": 0,
            "unchanged_wheel_build_paths": public_build_paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory)))


if __name__ == "__main__":
    main()
