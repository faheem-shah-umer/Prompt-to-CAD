# Windows x64 contributor setup

This guide describes the supported source path. A fresh Windows runner has passed setup, compilation, backend validation, packaging and extracted-ZIP smoke checks at commit `0cc68cc`. See [release validation](release-validation.md) for the exact run and remaining publication gates.

## Prerequisites and versions

| Component | Supported target / declaration |
| --- | --- |
| OS / architecture | Windows 10/11 x64; an OpenGL-capable driver for native viewport checks |
| Python | CPython 3.11 x64; clean-runner reference 3.11.9. Local integration used 3.11.7. |
| Compiler | Visual Studio 2022 Build Tools, Desktop development with C++; recommended 17.14 / v143 14.44, Windows SDK 10.0.26100. Local fallback integration used MSVC 19.40 / SDK 10.0.22621 and is not clean-runner proof. |
| Qt | conda-forge `qt6-main=6.9.0=h83cda92_0` (Core, Gui, Widgets, Svg) |
| OpenCascade | conda-forge `occt=7.8.1=novtk_hdfbec02_103` |
| SDK bootstrap | micromamba 2.3.3-0, executable SHA-256 checked by `tools.setup_windows` |
| Python CAD runtime | CadQuery 2.7.0 / cadquery-ocp 7.8.1.1.post1; full resolved versions in `requirements-runtime-lock.txt` |
| Build tools | CMake 4.4.4, Ninja 1.13.2, packaging 26.3 in `native/requirements-build.txt` |

Install Git and Python from their official sources. Install Visual Studio Build Tools using Microsoft's installer, selecting **Desktop development with C++**, **MSVC v143 x64/x86 build tools** and a **Windows SDK**. The setup script discovers an installed workload with `vswhere`; it does not download or redistribute the compiler.

Choose a reasonably short checkout path. The pinned micromamba uses a flat package cache to avoid Windows path-length failures on Qt's private headers. Do not commit the SDK, package cache or compiler environment.

## Create the Python environment and SDK

```powershell
git clone https://github.com/faheem-shah-umer/Prompt-to-CAD.git
cd Prompt-to-CAD
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m tools.setup_windows --download-sdk
```

`requirements.txt` declares runtime roots, `requirements-runtime-lock.txt` records the reviewed transitive runtime set, `native/requirements-build.txt` contains build tools, and `requirements-dev.txt` adds development tools. The SDK's exact package URLs/hashes are in `tools/locks/sdk-win-64.lock`. This is a platform-specific dependency lock, not a claim of byte-identical application builds.

The bootstrap verifies micromamba before running it, uses conda-forge only, and installs into ignored `.sdk/windows`. Re-run without `--download-sdk` for checks only. It reports missing SDKs/tools and checks Python-package consistency.

Existing SDKs can be used through `CAD_SDK_PREFIX` (the directory containing `bin`, `include`, `lib`), `CAD_QT_PREFIX` / `CAD_OCCT_PREFIX`, or explicit `--qt-prefix` / `--occt-prefix`. `CONDA_PREFIX/Library` is discovered when activated. No personal SDK/cache path is a default. Use an **x64 Native Tools Command Prompt**, or let `vswhere` discover Visual Studio. The optional `--toolchain-env` is a local fallback for isolated toolchains and must never be committed or packaged.

## Build and launch

```powershell
.venv\Scripts\python.exe -m tools.build_native
.venv\Scripts\python.exe -m tools.run_native
```

All tooling defaults to `build/`. To use another location, pass the same `--build-dir` to build, launch, UI checks, demo capture and packaging. `tools.run_native` supplies SDK DLL/plugin paths and the source workspace explicitly. Running the executable without that wrapper requires the same runtime environment. The native executable no longer embeds a developer checkout path.

Launching an existing build does not require compiler discovery. `Prompt to CAD.vbs` preserves an existing sibling desktop runtime first, then falls back to the documented source build. The portable ZIP uses its own `Start-PromptToCAD.cmd` and bundled runtime.

The app's design and CAD behavior remain the same. Changes made for distribution concern discovery, isolation, resources, notices, original icons and build/package paths.

## Validation

```powershell
.venv\Scripts\python.exe -m tools.check_privacy
.venv\Scripts\python.exe -m tools.audit_history
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui --case laptop-solid
.venv\Scripts\python.exe -m tools.check_links
```

Backend/UI checks generate isolated synthetic projects under ignored temporary/artifact locations. They never read personal projects or run live AI inference. The full native UI smoke harness covers more controls than the focused portable check. Keep results distinct: successful compilation is not UI verification, and a relocated test on a configured machine is not a clean Windows environment.

For public screenshots, run `python -m tools.create_demo`; it creates a new fixture/session and labels the conversation synthetic. Only reviewed pixel-only images in the public-media allowlist may be staged.

## Portable ZIP candidate

```powershell
.venv\Scripts\python.exe -m tools.package_native --output release-staging/review-0.5.0 --smoke-test
.venv\Scripts\python.exe -m tools.verify_archive release-staging/PromptToCAD-0.5.0-windows-x64.zip
.venv\Scripts\python.exe -m tools.smoke_package release-staging/PromptToCAD-0.5.0-windows-x64.zip
```

Use a **new** output directory each time. Packaging never refreshes or deletes an existing bundle. It follows the reviewed source allowlist, computes the Python/native dependency closure, retains license texts, includes replaceable DLLs/resources/source, relocates the package for an offline smoke check, audits privacy, then writes a versioned ZIP and SHA-256 file. No installer option exists.

The packaged Python runtime is separate from the developer virtual environment. The ZIP includes runtime packages, not `.venv`, the SDK or compiler. `runtime-manifest.json` records versions/notices/file hashes and pending publication gates. User data, accounts and machine configuration are excluded. Missing licenses or unresolved native dependencies stop packaging. Corresponding-source compliance requires the additional release checklist in [dependency licensing](dependency-licensing.md).

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `cl`, `rc` or `dumpbin` missing | Install the VS C++ x64 workload / Windows SDK, then use its x64 prompt or check `vswhere` discovery. |
| Qt/OCCT SDK missing | Run the bootstrap, activate the SDK environment, or supply the documented prefix flags. |
| Qt headers cannot extract | Use the pinned bootstrap and a shorter checkout path. Do not switch to a URL-nested package cache without checking Windows path lengths. |
| Missing Qt platform plugin | Launch through `tools.run_native`; package layout uses `bin/qt.conf` and `bin/plugins/platforms/qwindows.dll`. |
| OpenCascade shader / OpenGL error | Update the graphics driver and check SDK shader resources; package shaders live under `bin/resources/Shaders`. A CI renderer failure is a failed check, not a pass. |
| Cannot replace the executable | Close the running copy after its task finishes; Windows locks mapped executables. |
| Package license/provenance failure | Use the bootstrap SDK and retain its package cache; do not bypass missing notices or source obligations. |
| AI features unavailable | Install Codex separately, select it in Settings if discovery fails, and authorize your own eligible account/API connection. No connection is needed for offline CAD operations. |

See [architecture](architecture.md), [privacy](privacy.md), [contribution workflow](../CONTRIBUTING.md) and [release gates](release-validation.md).
