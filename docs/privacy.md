# Privacy and source boundaries

Tracked files contain application source, dependency declarations, build/check scripts, documentation, original branding and approved synthetic media. Personal projects, chats, credentials and development environments do not belong in Git.

## Local application data

Projects and their conversations/documents/revisions use `Projects/` beside the source workspace. Backend settings use `.promptcad/`. Native appearance/window settings use Qt's Windows user-settings namespace `PromptToCAD/PromptToCADV2`; UI logs use local application data unless `CAD_UI_LOG` is configured. Windows-protected account material is stored separately under the user's `.promptcad/v2/identity`.

Deleting a project does not revoke an account. AI features send the request and submitted CAD/image context to the configured provider. Local storage does not make AI inference offline.

AI diagnostic [turn logs](turn-logs.md) live under each project's `logs/turns/` folder. They contain private project descriptions, bounded tool observations and concise assistant-stated decisions, including cq_warehouse selection reasons. Known credentials and local paths are redacted and code/image payloads omitted; arbitrary project text can still be sensitive. Keep logs out of Git and review them before sharing. No automatic upload is added.

Private [runtime identity diagnostics](runtime-consistency.md) in `.promptcad/runtime/backend-<pid>.json` contain interpreter/module paths and source fingerprints for checking that all CAD processes load the same checkout. These raw machine paths are not public project media and should not be published.

## Development files

Keep all project-managed development output inside this repository: `.local/` for preserved desktop/compiler tools, `.sdk/` for SDK downloads/cache, `build/` for builds, and `tmp/`/`artifacts/` for temporary checks. These are ignored and must never be staged. Do not create sibling build or test folders.

`.gitignore` is a first layer; `tools/source_policy.py` defines approved source and exact public-media names. Stage reviewed named files only. Source checks and redacted secret scans must not print credential values.

Public screenshots use newly generated synthetic fixtures. [Provenance](../site/assets/PROVENANCE.md) records their origin and hashes. Existing personal CAD files, chats and images must not be used for publicity.

## Checks and historical limits

```powershell
python -m tools.check_privacy
python -m tools.audit_history
python -m tools.scan_secrets
```

Existing Git history contains author metadata and historical media/examples outside the present source policy. Their provenance/privacy review remains unresolved. No history rewrite is performed. Keep the repository private until an explicit future visibility decision and historical review.

Exact repository URLs necessarily identify the repository; the source checker allows those URLs, not arbitrary owner identifiers. Dependency authorship/required notices retain their own attribution. Never publish raw login logs, secret matches or private audit data.
