<p align="center"><img src="assets/app-icon.svg" width="64" alt="Prompt to CAD purple pyramid"></p>

# Prompt to CAD

**A Windows CAD workspace for describing parts, inspecting geometry and refining a design through conversation.**

Prompt to CAD brings a native Qt/OpenCascade viewport, local project history and a scoped CAD agent into one desktop application. It is an **early preview**, not a replacement for engineering review or a production-certified CAD system.

[Windows portable / Releases](https://github.com/faheem-shah-umer/Prompt-to-CAD/releases) · [Build from source](docs/setup.md) · [Contribute](CONTRIBUTING.md) · [Privacy](docs/privacy.md) · [Project website source](site/index.html)

> **Release status:** the 0.5.0 Windows x64 portable ZIP has passed clean Windows CI and is available as a private review artifact. Public publication remains pending final dependency-source review, historical-data review and owner approval. No installer is provided. A published portable ZIP will be attached to GitHub Releases; do not treat source archives as runnable builds.

![The real Prompt to CAD desktop workspace showing a synthetic three-component mounting fixture, a component tree and an explicitly labelled synthetic conversation.](site/assets/workspace-dark.png)

*Original app capture. Synthetic prompt: “Create a 64 × 44 × 8 mm mounting plate with four holes, a central 20 mm column and a lofted cap. Use separate components.” Result: three CAD solids built through the local backend. This reproducible fixture demonstrates the interface and CAD pipeline; it is not a recorded live AI generation. [Media provenance](site/assets/PROVENANCE.md).*

## What you can do

| Area | Current capability |
| --- | --- |
| Describe and refine | Ask Codex to create geometry or edit submitted body/face/edge selections, using controlled CAD tools. |
| Inspect and assemble | View solids and meshes, select components, measure geometry, move parts, manage visibility and inspect properties. |
| Edit geometry | Supported holes, offsets, fillets, chamfers, named parameters and controlled CadQuery scripts; component split, merge and replacement transactions. |
| Keep context | Local projects, multiple conversations, accepted revisions, undo/redo, Save As and revision restoration. |
| Communicate a design | Component colors and revision-owned dimensions, labels and notes; reference images when the chosen model reports support. |
| Stay in control | Candidate validation before acceptance; failed/cancelled tasks preserve the accepted document. |

### Formats and limits

| Operation | Supported formats |
| --- | --- |
| Engineering import | STEP/STP and the application's editable JSON recipes |
| Visual mesh import | GLB, STL, OBJ, PLY with explicit unit scale |
| Solid export | STEP, STL |
| Mesh/scene export | GLB, STL |

Imported files do not acquire invented sketch/feature history. Arbitrary proprietary CAD formats, full sketch constraints, mechanical simulation, full GD&T and STEP PMI export are not implemented. Mesh-region selection is triangle-based. AI generation can fail, and a geometrically valid result does not establish tolerances, structural strength or manufacturability. See [capabilities and limits](docs/agentic-cad.md).

## For users: portable quick start

1. Open [GitHub Releases](https://github.com/faheem-shah-umer/Prompt-to-CAD/releases) and choose the latest published `PromptToCAD-<version>-windows-x64.zip` and its `.sha256` checksum. If no portable release is listed, use the source path below.
2. Verify the ZIP with PowerShell: `Get-FileHash .\PromptToCAD-<version>-windows-x64.zip -Algorithm SHA256` and compare it with the published checksum.
3. Extract the **whole folder** to a writable location. Keep `bin/`, `python/`, `app/`, resources and notices together.
4. Run `Start-PromptToCAD.cmd` or `bin/PromptToCAD.exe`. No administrator privileges, Python installation or development SDK should be needed by the portable build.
5. Skip AI setup to import/view models and use the supported local tools. For prompting, install Codex separately and connect **your own** account in Settings → AI connection.

The target is Windows x64 with an OpenGL-capable graphics driver. The preview is unsigned; native rendering and graphics-driver support are part of the package smoke check. Clean-runner results are recorded in [release validation](docs/release-validation.md), not inferred from a developer-machine build.

### AI connection

AI features require an installed **Codex executable** supporting App Server. The app offers its own ChatGPT authorization flow for eligible accounts, or a user-supplied OpenAI API key with separate billing. It does not borrow another application's login, include a developer key, or switch billing modes automatically. Access depends on the selected account, model and provider limits. Offline CAD import, viewing, measurement, supported direct edits and export do not need an AI connection.

## For contributors: clone, build, run

The supported setup starts on Windows x64 with Git, CPython 3.11 x64 and Visual Studio 2022 C++ Build Tools. The setup script downloads a checksum-pinned micromamba executable and resolves the reviewed Qt 6.9.0 / OpenCascade 7.8.1 SDK lock into an ignored directory. An existing Anaconda installation is not required.

```powershell
git clone https://github.com/faheem-shah-umer/Prompt-to-CAD.git
cd Prompt-to-CAD
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m tools.setup_windows --download-sdk
.venv\Scripts\python.exe -m tools.build_native
.venv\Scripts\python.exe -m tools.run_native
```

The executable is `build/bin/PromptToCAD.exe`. Build, launch, UI validation and packaging share `--build-dir`; explicit Qt/OCCT prefixes and an x64 developer prompt are also supported. Launching a built application does not initialize compiler tools. The existing desktop shortcut keeps using its working sibling runtime when available. See [the complete setup guide](docs/setup.md) and [verified CI results](docs/release-validation.md).

### Focused checks

```powershell
.venv\Scripts\python.exe -m tools.check_privacy
.venv\Scripts\python.exe -m tools.audit_history
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui --case laptop-solid
.venv\Scripts\python.exe -m tools.check_links
```

Checks use synthetic temporary data and do not run paid/live inference. [CONTRIBUTING.md](CONTRIBUTING.md) covers issues, branches, changes, validation and pull requests. Keep runtime dependencies in `requirements.txt` and the reviewed runtime lock; build/development tools belong in their separate requirement files.

## Local data, public source

Projects and conversations remain in local `Projects/` folders; backend preferences use `.promptcad/`. Native window/appearance preferences use Windows user settings, and UI logs use local application data. Account material is stored separately with Windows protection. These locations are excluded from source and release inventories. Requests and explicitly submitted context are sent to the configured AI provider when you use AI features; this is not a fully offline AI application.

The repository and candidate ZIP must contain **no personal projects, chats, accounts or credentials**. The only public app captures are new synthetic fixtures with [provenance](site/assets/PROVENANCE.md). Existing Git author metadata remains in history; no history rewrite was performed. See [privacy and audit scope](docs/privacy.md).

## License and acknowledgments

Application code, documentation, purple pyramid and current original interface icons use the [MIT license](LICENSE). Python, Qt, OpenCascade, CadQuery and their dependencies retain their own terms. Read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [dependency redistribution/source requirements](docs/dependency-licensing.md). The portable candidate includes notices and a dependency manifest; final corresponding-source review remains a publication gate.

CADAM informed this README's information architecture only. Its code, wording, branding, screenshots and model assets are not used.
