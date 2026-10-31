"""Check tracked files for local identity and credential artifacts; never print values."""

import argparse
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from tools.source_policy import is_public_source
except ModuleNotFoundError:
    from source_policy import is_public_source

ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")
USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"<>]+)", re.I)
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")


def application_icons(root):
    root = root.resolve()
    resource_file = root / "native/branding.qrc"
    icon_directory = root / "assets/icons"
    icons = set()
    resources = ET.parse(resource_file).getroot()
    for entry in resources.findall("./qresource[@prefix='/icons']/file"):
        if not entry.text or not entry.text.strip():
            continue
        path = (resource_file.parent / entry.text.strip()).resolve()
        if (
            path.parent == icon_directory
            and path.suffix == ".svg"
            and not path.name.startswith(".")
            and path.is_file()
        ):
            icons.add(path.relative_to(root).as_posix())
    return icons


def check(root, history=False):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)

    remote = git("config", "--get", "remote.origin.url").decode().strip()
    owner = re.search(r"github\.com[:/]([^/]+)/", remote)
    owner = owner[1].lower() if owner else None
    findings = []
    try:
        icons = application_icons(root)
    except (OSError, ET.ParseError):
        icons = set()
        findings.append(("native/branding.qrc", 0, "cannot read application icon declarations"))
    files = 0
    for raw in git("ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        relative = raw.decode()
        path = root / relative
        if not path.is_file():
            continue
        files += 1
        if not is_public_source(relative) and relative not in icons:
            findings.append((relative, 0, "not application source, documentation or approved branding"))
        name = path.name.lower()
        if (
            name in ("auth.json", "credentials.json", "credentials.dpapi", ".env", ".env.local", ".env.production")
            or path.suffix.lower() in (".dpapi", ".pem", ".key", ".p12", ".pfx")
            or any(part in (".promptcad", ".codex", ".claude", ".aws", ".azure") for part in path.parts)
        ):
            findings.append((relative, 0, "credential or runtime file tracked"))
        data = path.read_bytes()
        if PRIVATE_KEY.search(data):
            findings.append((relative, 0, "private key material"))
        if b"\0" in data[:8000]:
            continue
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if owner and owner in line.lower():
                findings.append((relative, number, "repository owner identity in file"))
            for email in EMAIL.findall(line):
                domain = email.rsplit("@", 1)[1].lower()
                if not (domain.endswith((".invalid", ".test")) or domain in ("example.com", "example.org", "example.net")):
                    findings.append((relative, number, "non-example email address"))
            for match in USER_PATH.finditer(line):
                if match[1].upper() not in ("USER", "USERNAME", "PUBLIC", "DEFAULT", "EXAMPLE", "YOURNAME"):
                    findings.append((relative, number, "local user directory"))
    if history:
        identities = git("log", "--branches", "--format=%H%x09%an%x09%ae%x09%cn%x09%ce").decode()
        for line in identities.splitlines():
            commit, author, email, committer, committer_email = line.split("\t")
            if (author, email, committer, committer_email) != (
                "Prompt to CAD contributors", "noreply@prompt-to-cad.invalid",
                "Prompt to CAD contributors", "noreply@prompt-to-cad.invalid",
            ):
                findings.append(("commit " + commit[:12], 0, "personal commit identity remains"))
    return files, findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also require neutral identities on local branch history.")
    args = parser.parse_args()
    files, findings = check(ROOT, args.history)
    for path, line, reason in findings:
        print(f"{path}:{line}: {reason}")
    print(f"Privacy checks: {files} tracked files, {len(findings)} findings. Secret values are never printed.")
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()
