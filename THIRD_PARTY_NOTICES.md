# Third-party notices

The MIT licence in this repository covers the project's own code, documentation and pyramid artwork. It does not relicense dependencies or hosted services.

Python and JavaScript dependencies are installed separately from their respective package registries. Their licence files and notices are provided with their distributions; retain those notices when distributing a bundled application. Dependency versions are recorded in `backend/requirements*.txt`, `requirements-desktop.txt`, `frontend/package.json` and `frontend/package-lock.json`.

Microsoft WebView2 is a separately installed Microsoft runtime governed by its own terms.

Users supply their own model service or local inference server. Provider access, model licences, charges and usage terms are separate from this project's MIT licence.

The icon in `frontend/public/app-icon.svg` was drawn for this project from basic geometric polygons. Its PNG and ICO counterparts are rendered from that SVG.

## Native Windows distribution

The native bundle dynamically links Qt 6 and OpenCascade 7.8.1, and includes a Python 3.11 runtime and the installed CAD/API Python distributions. Their original licence texts and package metadata are retained in the bundle. OpenCascade's LGPL 2.1 text and additional exception are in licences/occt; Qt's licence texts are in licences/qt. The bundle also includes the application source and build scripts. Replacing the application's MIT licence does not replace these dependency terms.

The installer is built with NSIS. It does not include AutoCAD code, commercial CAD translators, model weights or access to a hosted model service.
