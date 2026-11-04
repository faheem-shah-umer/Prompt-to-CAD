# Windows x64 source setup

This is a personally maintained source project. Set up your own environment and build it yourself; there is no prebuilt distribution or contributor program.

## Requirements

| Dependency | Supported reference |
| --- | --- |
| Windows | Windows 10/11 x64 with an OpenGL-capable graphics driver |
| Git | Git for Windows, available on `PATH` for cloning and the pinned cq_warehouse dependency |
| Python | CPython 3.11 x64; fresh CI reference 3.11.9 |
| C++ compiler | Visual Studio 2022 Build Tools, v143 14.44, Windows SDK 10.0.26100; fresh CI used MSVC 19.44.35229 |
| Qt | `qt6-main=6.9.0=h83cda92_0` from conda-forge |
| OpenCascade | `occt=7.8.1=novtk_hdfbec02_103` from conda-forge |
| Python CAD runtime | CadQuery 2.7.0 / cadquery-ocp 7.8.1.1.post1; exact set in `requirements-runtime-lock.txt` |
| Standard components | cq_warehouse 0.8.0 at commit `a57bb7a24762d367d66369f280a24c38a64e73dd` (Git is needed during pip installation) |
| Build tools | CMake 4.4.4, Ninja 1.13.2, packaging 26.3 |

Install Git, CPython and Visual Studio Build Tools with Desktop development with C++, x64/x86 v143 tools and a Windows SDK. Anaconda is not required.

## Setup → build → run

Start in the cloned checkout. The complete clone and setup sequence is in the [README](../README.md#build-and-run).

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m tools.setup_windows --download-sdk
.venv\Scripts\python.exe -m tools.build_native
.\Run-PromptToCAD.cmd
```

The bootstrap verifies micromamba 2.3.3-0 and the exact SDK URLs/SHA-256 values in `tools/locks/sdk-win-64.lock`. Downloads and caches stay under `.sdk/`. Keep the checkout path reasonably short for Windows SDK headers.

The default source executable is `build\bin\PromptToCAD.exe`. `Run-PromptToCAD.cmd` resolves the checkout relative to itself, uses `.venv\Scripts\python.exe -m tools.run_native` and supplies runtime DLL/plugin paths without initializing compiler tools. No environment activation, private runtime or absolute-path shortcut is required. Run it from any directory, or double-click it; failures remain visible (set `CI=true` to suppress the failure pause in automation). Launching never installs dependencies or builds. Re-run `tools.build_native` explicitly after changing C++ source.

The `.cmd` forwards the existing SDK and `--build-dir` options to `tools.run_native`; pass the same `--build-dir` when building and launching elsewhere. Native application arguments follow `--`, for example `.\Run-PromptToCAD.cmd -- --version`.

The existing personal `Prompt to CAD.vbs`/desktop shortcut separately uses `.local/desktop-build/bin/` when its preserved desktop runtime is present, otherwise the source build. Its runtime selection and existing local data are unchanged. No sibling build directories are required.

Existing SDKs can use `CAD_QT_PREFIX`, `CAD_OCCT_PREFIX`, `CAD_SDK_PREFIX`, explicit prefix arguments, or activated `CONDA_PREFIX/Library`. A private compiler environment can be passed with `--toolchain-env`. The owner's preserved `.local/toolchain/environment.json` is discovered for compilation only; other machines do not need it. Never commit `.local/`.

`requirements.txt` contains runtime roots, `requirements-runtime-lock.txt` pins the runtime set, and `requirements-dev.txt` adds build/development tools.

The standard-part adapter keeps CadQuery/OCP versions unchanged. See [standard parts](standard-parts.md) for chat tools, editable generator metadata, isolated validation and the optional native compound viewer check. Existing native projects do not need generator history to open their saved BREP geometry.

## Focused checks

```powershell
.venv\Scripts\python.exe -m tools.check_privacy
.venv\Scripts\python.exe -m tools.check_links
.venv\Scripts\python.exe -m tools.validate
.venv\Scripts\python.exe -m tools.validate_ui --case laptop-solid
```

Run checks deliberately. They use synthetic data and no paid inference. The manual **Windows source check** workflow installs dependencies and builds on a fresh `windows-2022` x64 runner, runs privacy/link checks, exercises `tools.validate_ui --case laptop-solid --launcher`, and validates the backend/launcher tests. The viewport check invokes the `.cmd` from outside the checkout with isolated synthetic state. For the CI runner's graphics environment, it copies the pinned Qt SDK's `opengl32sw.dll` to the ignored `build/bin/opengl32.dll` so OpenCascade's native Windows OpenGL context also uses software rendering. Normal source builds use the installed graphics driver. A successful run verifies the specific source commit shown in that run, not subsequent local edits.

For synthetic README/site media, `python -m tools.create_demo` uses isolated sessions under `artifacts/`. Never reuse private projects or chats.

## Troubleshooting

- Missing `cl`/`rc`: install the C++ workload/SDK or use its x64 developer prompt.
- Missing `.venv`/Python: install CPython 3.11 x64 and create `.venv` with `py -3.11 -m venv .venv`.
- Missing or incompatible Python dependencies: run `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`.
- Missing Qt/OCCT: run setup or supply the correct prefixes.
- Missing `build\bin\PromptToCAD.exe`: run `.venv\Scripts\python.exe -m tools.build_native`; launching does not compile it for you.
- Qt plugin error: use `tools.run_native` so runtime paths are configured.
- Shader/OpenGL error: check the driver and SDK shader resources.
- Locked executable: finish its current task and close that copy before moving it.
- AI unavailable: install Codex or Claude Code separately and connect your own account/key in Settings → AI connection. Offline CAD tools do not need AI.

See [architecture](architecture.md), [capabilities](agentic-cad.md), [privacy](privacy.md) and [dependency notices](../THIRD_PARTY_NOTICES.md).
