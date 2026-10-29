# Repository privacy

Use the `prompt-to-cad-v2` branch. Git contains application source, documentation, tests and approved branding assets. User-created models, example CAD files, project/document/revision data, conversations, imported/reference files, exports and generated reports/screenshots are excluded. Runtime accounts and user projects belong outside the checkout; the application defaults to `%USERPROFILE%/.promptcad/v2`.

The source policy in `tools/source_policy.py` is shared by the tracked-file checker and packager. It allows source files in designated source directories and the original logo assets. JSON/JSONL records, CAD/mesh files, databases, reference images and generated validation outputs are ignored and rejected if force-added. Add any future legitimate source asset to this reviewed policy explicitly. Validation creates fresh synthetic geometry in ignored temporary folders instead of reusing saved user designs.

Public OAuth client identifiers, endpoints, model names and the code handling authentication are application configuration, not account credentials. Do not replace them with a developer key or remove the login implementation. API keys, access/refresh/ID tokens, authorization codes, actual account email addresses, session exports and encrypted credential stores must never be committed.

Run the tracked-file check before publishing:

```powershell
.venv\Scripts\python.exe -m tools.check_privacy
.build-tools\gitleaks\gitleaks.exe git . --log-opts="--all --reflog" --redact --no-banner
```

[Gitleaks](https://github.com/gitleaks/gitleaks) is a separate developer tool. Install an official release and verify its checksum; no account credentials are needed for a scan. CI also scans Git history with redacted output. The local privacy check reports file/line locations and reasons, never matching values. Test-only identities use reserved example domains.

For future local commits, set a repository-specific identity:

```powershell
git config --local user.name "Prompt to CAD contributors"
git config --local user.email "noreply@prompt-to-cad.invalid"
```

`tools.check_privacy --history` also checks commit identities on local branches. Editing a file or renaming a branch does not erase its earlier versions or author metadata. Sanitizing already-pushed history changes commit IDs and requires a coordinated force-push. Other clones, pull-request refs, caches and the hosting account's owner name are separate surfaces; a clean scan does not establish anonymity or prove that every possible secret is absent.

Never add raw scanner findings or login protocol logs to validation reports. Retain counts, scan scope and reviewed findings instead. If a live credential is discovered in Git, revoke it as well as removing it from history.
