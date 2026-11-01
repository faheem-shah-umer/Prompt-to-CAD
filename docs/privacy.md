# Privacy and repository boundaries

The public tree contains application source, dependency declarations, build/check scripts, documentation, original branding and explicitly reviewed synthetic demonstration media. It does not contain personal projects, prompts, chats, account state, credentials, reference images or exports.

## Local application data

Projects and their documents/conversations/revisions use `Projects/` beside the source workspace or extracted portable application. Backend preferences use `.promptcad/`. Native appearance/window preferences use Qt's Windows user-settings registry namespace (`PromptToCAD/PromptToCADV2`); UI logs use the application's local-data directory under `%LOCALAPPDATA%`, unless `CAD_UI_LOG` is explicitly configured. Account material uses separate Windows-protected storage under the user's `.promptcad/v2/identity`; deleting a project does not imply deleting or revoking an account. Moving a project can preserve its local conversation history. Portable refers to the bundled runtime, not to storing every preference or credential inside the extracted folder.

AI requests send the prompt and explicitly submitted CAD/image context to the configured provider. Local storage does not mean AI inference is offline. No personal account is included in source or distributions. Users authorize their own connection.

## Inclusion and exclusion

`.gitignore` broadly excludes projects, credentials, CAD files, generated media, caches, virtual environments, downloaded SDKs, build output and release staging. Ignore rules are only a first layer: `tools/source_policy.py` defines the reviewed public-source and exact media allowlist, shared by privacy checks and packaging. Never force-add user files or stage the entire working tree.

Public media under `site/assets/` is newly captured from the real app using `tools.create_demo` and a synthetic local fixture. Every run isolates projects, account identity and Qt settings. Captures are labelled as synthetic (no live AI inference) and re-encoded without image metadata. [Provenance](../site/assets/PROVENANCE.md) records their hashes and generation method. Existing project or chat screenshots must never be reused for publicity.

Portable packaging copies a reviewed file inventory and runtime dependency closure. It never copies `.venv`, the SDK environment, a user's project folders or credentials. It refuses to overwrite an existing staging directory. Dependency license texts may contain their upstream authors' attribution; that required legal text is not the owner's private account data. The exact dependency-owned `certifi/cacert.pem` is a public CA bundle, not an account key.

## Audit commands and limits

```powershell
python -m tools.check_privacy
python -m tools.audit_history
python -m tools.scan_secrets
python -m tools.audit_package release-staging/<candidate>
```

The source checker reports file/line and category without matching values. The history audit covers all reachable refs and unique blobs, reports non-neutral author metadata and files outside the current policy, and never rewrites history. Gitleaks is checksum-verified and runs with redaction; only summary counts/rule IDs are suitable for public reports. A clean secret scan is not proof that all historical media or every possible secret is harmless.

The current audit found existing author metadata and historical screenshots/CAD examples/validation artifacts outside today's source policy. They were not copied into the current public-media set or portable runtime. Their provenance/privacy review remains unresolved. The repository is private, with a review branch for Windows CI. Public publication remains pending; no history rewrite, force-push, visibility change, Pages deployment or release publication is part of this review.

Repository URLs necessarily identify the existing repository. Checks allow those exact repository/project-site URLs, rather than treating them as embedded credentials. They do not allow arbitrary owner identifiers elsewhere. Do not publish raw audit reports, login protocol logs or private matching values.

If a live credential is found, stop publication and revoke it. Removal from the current tree cannot erase previous publication. Any future history remediation requires a separate, explicitly approved process; it is not performed by this work.
