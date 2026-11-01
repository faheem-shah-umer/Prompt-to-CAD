# Contributing to Prompt to CAD

Start with [Windows setup](docs/setup.md), the [architecture](docs/architecture.md) and [current capability limits](docs/agentic-cad.md). The project is an early preview; small, reviewable changes are easiest to evaluate.

## Issues

Use the repository's Issues tab for reproducible bugs and feature proposals. Include the app version, Windows/graphics details, expected behavior and minimal reproduction steps. Use a new synthetic CAD example. Never attach personal projects, chats, account emails, tokens, provider logs, credentials or private reference images. If a report needs sensitive material, describe the symptom without uploading it publicly.

## Changes and pull requests

1. Fork/clone and create a descriptive branch, such as `fix/chat-scroll` or `feature/export-check`.
2. Keep the native design and supported behavior consistent. Explain any scope or compatibility change.
3. Add meaningful focused checks for changed contracts; run the relevant validation commands from setup.md. Live AI tests require your own account, explicit intent and separately recorded results.
4. Update user/developer documentation when behavior or prerequisites change.
5. Review `git diff`, `git diff --check` and named staged paths. **Never use `git add .` for this repository.** Stage only reviewed source, documentation and approved original assets.
6. Run the tracked-file privacy check. Run a redacted history secret scan before publishing a branch that introduces previously unreviewed history.
7. Open a PR explaining the problem, final behavior, checks actually run, and remaining limitations. Do not claim clean-runner success based on a configured workstation.

Keep root runtime requirements, the runtime lock and development/build requirements separate. Dependency/SDK changes need license, source-access and package-closure review. No SDK downloads, virtual environments, generated build output or machine configuration belongs in Git.

## Public media

Use `tools.create_demo` with a fresh isolated fixture. Inspect the complete output, remove metadata by re-encoding pixels, record provenance and approve the exact filename in `tools/source_policy.py`. Existing project/chat images are never demo material. Synthetic seeded conversations must be labelled as such; do not imply a live AI generation occurred.

## Releases and website

The static website is under `site/`; all assets are local and paths are relative so the GitHub Pages project subpath works. Preview with `python -m http.server 8080 --directory .` and open `/site/`, or mount the prepared site at `/Prompt-to-CAD/` as described in `docs/website.md`.

The prepared Windows workflow builds and tests from a fresh checkout and uploads a **review artifact**. The Pages workflow is manual and targets a protected `github-pages` environment. Neither a local candidate ZIP nor a successful build grants publication approval. Follow [release validation](docs/release-validation.md); publish only after privacy, licensing, clean setup/package checks and owner approval. Do not create an installer, rewrite history or include user data.
