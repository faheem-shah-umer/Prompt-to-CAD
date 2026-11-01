"""Audit a portable staging tree without printing private matching values."""
import argparse
import json
import os
from pathlib import Path
import re

BLOCKED = {".git", ".promptcad", ".codex", ".aws", ".azure", "projects", "conversations", "sessions", "__pycache__"}
PRIVATE = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{64,}")


def audit(root):
    root = Path(root).resolve()
    findings = []
    count = 0
    user = Path.home().name
    private_paths = [(drive + ":/Users/" + user).lower() for drive in ("C", "D")]
    private_paths += [str(Path(__file__).resolve().parents[1]).replace("\\", "/").lower()]
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
        if any(value in text or value in wide for value in private_paths):
            findings.append("host-specific path")
    if findings:
        categories = {name: findings.count(name) for name in set(findings)}
        raise RuntimeError("Portable privacy audit failed (values withheld): " + json.dumps(categories))
    return {"passed": True, "files": count, "private_matches": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory)))


if __name__ == "__main__":
    main()
