# Prompt to CAD

<img src="assets/app-icon.svg" alt="Prompt to CAD purple pyramid logo" width="80">

The current Windows desktop CAD workspace, with distinct dark/light workspace panels, rounded conversation bubbles, inline task activity and a startup loading screen, for text-driven creation and selected-part editing with Codex.

Open **Prompt to CAD.lnk** (created by the native build with our logo), **Prompt to CAD.vbs**, or run `.venv\Scripts\python.exe native-app.py`.

For a fresh checkout, install [requirements-dev.txt](requirements-dev.txt), configure the Qt/OpenCascade SDKs, and run `.venv\Scripts\python.exe -m tools.build_native --test`.

Connect **ChatGPT subscription — Codex** or **OpenAI API key — separately billed** in Settings. Both use the same App Server and scoped CAD tools. Billing never switches automatically.

| Path | Purpose |
| --- | --- |
| assets/ | Original purple pyramid logo shared by the application, launcher, installer and docs |
| native/ | Current C++/Qt application and OpenCascade viewport |
| backend/native/ | Shared CAD geometry, recipes, documents and worker |
| backend/v2/ | Current projects, conversations, authentication and Codex/CAD tools |
| backend/tests/ | Current workspace and CAD-engine tests |
| tools/ | Current build, packaging and validation commands |
| docs/ | Current setup, architecture, design and validation |
| dist-native/ | Current release only; generated and Git-ignored |

New projects are saved in **Projects/<project name>/** inside this repository (or beside the packaged application). Conversations, documents and revisions stay with the named project. App runtime settings live in the ignored **.promptcad/** folder; account credentials remain in Windows-protected user storage. Repository-local design/export folders were preserved in **Prompt-to-CAD Saved Designs**, beside the repository. Git history retains retired source; older applications are not maintained alongside this checkout.

Git contains application source, documentation, tests and our branding. Chats, project files, CAD models, imports, exports, reference images and generated validation outputs are excluded. Tests generate synthetic geometry in ignored temporary folders; the application and release contain no preloaded user projects or conversations. See [repository privacy](docs/privacy.md).

See [setup and capabilities](docs/setup.md), [architecture](docs/architecture.md), [validation](docs/validation.md), and [third-party notices](THIRD_PARTY_NOTICES.md). This is developing CAD software; arbitrary-format compatibility and production readiness are not claimed.
