# Third-party notices

The MIT licence in this repository covers the project's own code, documentation and pyramid artwork. It does not relicense dependencies or hosted services.

Python and JavaScript dependencies are installed separately from their respective package registries. Their licence files and notices are provided with their distributions; retain those notices when distributing a bundled application. Dependency versions are recorded in `backend/requirements*.txt`, `requirements-desktop.txt`, `frontend/package.json` and `frontend/package-lock.json`.

Microsoft WebView2 is a separately installed Microsoft runtime governed by its own terms.

Users supply their own model service or local inference server. Provider access, model licences, charges and usage terms are separate from this project's MIT licence.

The icon in `frontend/public/app-icon.svg` was drawn for this project from basic geometric polygons. Its PNG and ICO counterparts are rendered from that SVG.

## Native Windows distribution

The native bundle dynamically links Qt 6 and OpenCascade 7.8.1, and includes a Python 3.11 runtime and the installed CAD/API Python distributions. Their original licence texts and package metadata are retained in the bundle. OpenCascade's LGPL 2.1 text and additional exception are in licences/occt; Qt's licence texts are in licences/qt. The bundle also includes the application source and build scripts. Replacing the application's MIT licence does not replace these dependency terms.

The installer is built with NSIS. It does not include AutoCAD code, commercial CAD translators, model weights or access to a hosted model service.

## Prompt to CAD V2

The V2 dependency manifest is requirements-v2.txt. It adds PyJWT (MIT), cryptography (Apache-2.0/BSD), Trimesh (MIT), SciPy (BSD-3-Clause) and their dependency notices. Package metadata and bundled licence texts govern the exact installed distributions. The Codex executable is supplied by the user and is not copied from the developer's desktop installation into the package. OpenAI service terms and eligible plan usage are separate from the repository's MIT licence.

Tripo is an optional remote service with separate user authentication, billing and output terms. No Tripo/TripoSR model weights, Claude runtime, commercial CAD translator or AutoCAD/SolidWorks implementation is bundled. Public CAD interface references informed the layout; no proprietary CAD code was extracted.
