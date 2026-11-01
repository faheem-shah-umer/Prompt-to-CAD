# Windows portable release preparation

Version: **0.5.0 candidate**. This file describes required gates; actual local outcomes are recorded separately under ignored `artifacts/release-checks/`. Do not convert planned checks into passed claims.

## Reviewable outputs

- Public application source, contributor guide and locked Windows setup path.
- README and static site with original, explicitly synthetic dark/light native captures.
- A portable staging tree, versioned Windows x64 ZIP, runtime/dependency/file manifest, notices/source-access directions and SHA-256 checksum.
- Manual clean-Windows artifact and Pages workflows. No installer is produced.

## Publication gates

1. Current-tree and archive privacy checks pass; review all reachable history findings and decide how to handle existing metadata/artifacts without rewriting history.
2. Redacted secret scan passes. Review any finding without publishing raw matching values.
3. Fresh Windows runner builds from the documented setup and pinned locks, without existing SDKs or user configuration.
4. Native synthetic import/selection and bundled Python/offline CAD import/export work after extracting to a different folder with spaces, with development SDKs removed from PATH.
5. Exact dependency license/notice inventory and corresponding-source access are verified. Publish required source compliance artifacts alongside binaries where necessary.
6. README/site links, local project-subpath preview, keyboard access, contrast and responsive behavior are checked, with any untested physical-device behavior stated.
7. Owner approves publication after reviewing the artifacts. Only then tag the version, publish a GitHub Release containing the ZIP/checksum and required compliance material, and manually deploy Pages.

The repository is private and currently maintained by its owner alone. A `codex/distribution-review` branch is used for private review and Windows CI. Public publication remains pending: no tag, release, visibility change or Pages deployment is part of this review push. The Windows workflow runs on that review branch; the Pages workflow remains manual.

## Reproduce a review candidate

Follow setup.md, then run:

```powershell
python -m tools.check_privacy
python -m tools.audit_history
python -m tools.scan_secrets
python -m tools.check_links
python -m tools.package_native --output release-staging/review-0.5.0 --smoke-test
```

The output path must not already exist. Candidate manifests keep `publication_ready: false` and explicitly list pending clean-runner/licensing/approval gates. Do not edit that field merely to make publication possible. A local relocated smoke result is useful evidence, but is not a fresh operating-system result.

## Local review evidence — 1 November 2026

| Check | Result / boundary |
| --- | --- |
| Prerequisite check and native Release build | Passed on the configured Windows host using the fresh locked SDK; not fresh-OS proof. |
| Backend validation | 79 tests passed; no live provider inference. |
| Relocated portable smoke | Bundled Python imports, offline CAD import/export, three rendered solids and native face selection passed from a separate folder with spaces and no development SDK on PATH. |
| Current source privacy | Passed with zero findings; only reviewed named files staged. |
| History review | 39 commits / 687 unique blobs examined; 16 existing non-neutral author records and 82 historical blobs outside the current policy remain unresolved. No rewrite performed. |
| Website browser check | Six widths, 320–1920 px; no overflow or measured solid-background text-contrast failures; images, alt attributes, keyboard skip link and keyboard screenshot switch passed. |
| Website review limits | Main-agent visual review only; independent reviewer unavailable due to a usage limit. No physical-phone test. |
| Documentation links | All local links/assets passed. 22 of 25 public external targets responded; repository, issues and releases URLs returned unauthenticated HTTP 404. Public visitor access is not yet verified. |
| Remaining release gates | Fresh Windows CI run, exact corresponding-source/third-party redistribution clearance, historical-content decision and owner publication approval. |

Raw local reports and browser captures stay in ignored `artifacts/`; they are not release assets or public documentation. The final archive must additionally pass `tools.verify_archive` and retain its checksum and manifest. Nothing in this local evidence claims that GitHub Pages or a GitHub Release has been published.
