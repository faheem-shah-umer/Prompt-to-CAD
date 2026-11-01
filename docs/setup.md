# Windows x64 source setup

This is a personally maintained source project. Set up your own environment and build it yourself; there is no prebuilt distribution or contributor program.

## Requirements

| Dependency | Supported reference |
| --- | --- |
| Windows | Windows 10/11 x64 with an OpenGL-capable graphics driver |
| Python | CPython 3.11 x64; fresh CI reference 3.11.9 |
| C++ compiler | Visual Studio 2022 Build Tools, v143 14.44, Windows SDK 10.0.26100; fresh CI used MSVC 19.44.35229 |
| Qt | `qt6-main=6.9.0=h83cda92_0` from conda-forge |
| OpenCascade | `occt=7.8.1=novtk_hdfbec02_103` from conda-forge |
| Python CAD runtime | CadQuery 2.7.0 / cadquery-ocp 7.8.1.1.post1; exact set in `requirements-runtime-lock.txt` |
| Build tools | CMake 4.4.4, Ninja 1.13.2, packaging 26.3 |

Install Git, CPython and Visual Studio Build Tools with Desktop development with C++, x64/x86 v143 tools and a Windows SDK. Anaconda is not required.

## Set up and run

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m tools.setup_windows --download-sdk
.venv\Scripts\python.exe -m tools.build_native
.venv\Scripts\python.exe -m tools.run_native
```

The bootstrap verifies micromamba 2.3.3-0 and the exact SDK URLs/SHA-256 values in `tools/locks/sdk-win-64.lock`. Downloads and caches stay under `.sdk/`. Keep the checkout path reasonably short for Windows SDK headers.

The default executable is `build/bin/PromptToCAD.exe`; pass the same `--build-dir` when building and launching elsewhere. The launcher supplies runtime DLL/plugin paths without initializing compiler tools. `Prompt to CAD.vbs` uses `.local/desktop-build/bin/` when an existing desktop runtime is present, otherwise the source build. No sibling build directories are required.

Existing SDKs can use `CAD_QT_PREFIX`, `CAD_OCCT_PREFIX`, `CAD_SDK_PREFIX`, explicit prefix arguments, or activated `CONDA_PREFIX/Library`. A private compiler environment can be passed with `--toolchain-env`. The owner's preserved `.local/toolchain/environment.json` is discovered for compilation only; other machines do not need it. Never commit `.local/`.

`requirements.txt` contains runtime roots, `requirements-runtime-lock.txt` pins the runtime set, and `requirements-dev.txt` adds build/development tools.

## Focused checks

```powershell
.venv\Scripts\python.exe -m tools.check_privacy
.venv\Scripts\python.exe -m tools.check_links
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui --case laptop-solid
```

Run checks deliberately. They use synthetic data and no paid inference. The manual Windows source-check workflow builds from a fresh runner. Source compilation and backend checks have already been exercised on fresh Windows CI.

For synthetic README/site media, `python -m tools.create_demo` uses isolated sessions under `artifacts/`. Never reuse private projects or chats.

## Troubleshooting

- Missing `cl`/`rc`: install the C++ workload/SDK or use its x64 developer prompt.
- Missing Qt/OCCT: run setup or supply the correct prefixes.
- Qt plugin error: use `tools.run_native` so runtime paths are configured.
- Shader/OpenGL error: check the driver and SDK shader resources.
- Locked executable: finish its current task and close that copy before moving it.
- AI unavailable: install Codex separately and authorize your own account/key. Offline CAD tools do not need AI.

See [architecture](architecture.md), [capabilities](agentic-cad.md), [privacy](privacy.md) and [dependency notices](../THIRD_PARTY_NOTICES.md).
