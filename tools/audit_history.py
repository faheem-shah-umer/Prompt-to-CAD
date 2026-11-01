"""Audit reachable history content and author metadata; never print matching values."""
import json
import re
import subprocess
from tools.build_native import ROOT
from tools.check_privacy import USER_PATH, PRIVATE_KEY
from tools.source_policy import is_public_source


def main():
    def git(*args): return subprocess.check_output(["git", *args], cwd=ROOT)
    commits = git("log", "--all", "--format=%H%x09%an%x09%ae%x09%cn%x09%ce").decode().splitlines()
    identities = sum(line.split("\t")[1:] != ["Prompt to CAD contributors", "noreply@prompt-to-cad.invalid"] * 2 for line in commits)
    objects = {}
    for line in git("rev-list", "--objects", "--all").decode().splitlines():
        identity, separator, path = line.partition(" ")
        if separator: objects[identity] = path
    process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    data, _ = process.communicate(("\n".join(objects) + "\n").encode())
    cursor = 0
    findings = {"private_key_blocks": 0, "user_directory_literals": 0, "unreviewed_historical_files": 0}
    blobs = 0
    while cursor < len(data):
        end = data.index(b"\n", cursor)
        header = data[cursor:end].decode().split()
        cursor = end + 1
        if len(header) != 3: continue
        identity, kind, size = header
        content = data[cursor:cursor + int(size)]
        cursor += int(size) + 1
        if kind != "blob": continue
        blobs += 1
        if not is_public_source(objects[identity]): findings["unreviewed_historical_files"] += 1
        if PRIVATE_KEY.search(content): findings["private_key_blocks"] += 1
        for match in USER_PATH.finditer(content.decode("utf-8", errors="ignore")):
            if match[1].upper() not in {"USER", "USERNAME", "PUBLIC", "DEFAULT", "EXAMPLE", "YOURNAME"}:
                findings["user_directory_literals"] += 1
    report = {"commits": len(commits), "unique_blobs": blobs, "existing_non_neutral_author_records": identities,
        "content_findings": findings, "history_rewritten": False,
        "publication_approval": "pending; retain existing metadata only with owner approval"}
    output = ROOT / "artifacts/release-checks"
    output.mkdir(parents=True, exist_ok=True)
    (output / "history-audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    raise SystemExit(1 if any(findings.values()) else 0)


if __name__ == "__main__":
    main()
