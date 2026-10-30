# Local runtime update — 2026-10-30

The user explicitly requested updating the runnable application after the source-only implementation. A Release native build completed successfully from `agentic-cad-capabilities`, with application sources at commit `6140a1f` (backend capabilities at `6827c9b`). The executable includes the earlier project ordering, visibility and conversation changes at `992ef37` as well as the new agentic CAD interface.

- Compiler: MSVC 19.44; C++20; Qt 6.9; OpenCASCADE 7.8.1.
- Result: all 21 build steps completed, including native linking. Existing Qt deprecation and variable-shadowing warnings remain; no compilation errors occurred.
- Deployment: `.app-runtime/PromptToCAD.exe`, 872,448 bytes; SHA-256 `5a10d766b117cb482756de73a7962c8573720cf4cea37e417aba6e4a06cc3eea`. The deployed bytes match the linked executable.
- Qt JPEG and WebP plugins and the WebP demux dependency were added to the ignored local runtime. PNG decoding is provided by Qt itself. The deployment helper now includes these image plugins and their dependency closure.
- Static import inspection covered 52 local executable/DLL files and found no unresolved native dependencies; no application task was executed for this inspection.
- The original shortcut, launcher and logo are retained. Backend source and existing Python dependencies remain in use. Projects and credential storage were not changed by deployment.

Temporary compiler, SDK and build intermediates were kept outside the repository and removed after deployment. Runnable files remain ignored by Git. This update does not enable automatic builds or tests.

No tests, live inference, authentication, UI verification, installer, merge or push were performed. Successful compilation and file inspection do not establish the modelling, provider or UI acceptance scenarios in [agentic CAD capabilities](agentic-cad.md) or [validation](validation.md).

## Chat composer update — 2026-10-30

The attachment control now uses a bundled paperclip icon. Unsent composer text is kept in memory per project/conversation alongside attachment drafts. Switching conversations restores only the destination conversation’s draft; refreshing the same conversation does not reset it. Drafts are not newly persisted to disk by this change.

A Release build completed all 21 compile/link steps and was deployed behind the existing shortcut after the user closed the app. The deployed executable is 873,472 bytes; SHA-256 `dc2790a1882cbe6f7028e79b437579173f8afd5d2e4e2754911d75942af394fc`. Deployed bytes match the linked executable. Existing compiler warnings remain. No tests, UI verification or inference were run. Temporary build tools and intermediates were removed after deployment; projects and credentials were preserved.

## Attachment icon sizing fix — 2026-10-30

The compact 28-pixel attachment button inherited 12-pixel horizontal padding from the shared button style, leaving only about two pixels for its 18-pixel icon. A specific four-pixel padding rule now provides the icon’s full content area in both themes.

A Release build completed all 21 compile/link steps and replaced the executable behind the existing shortcut after the user closed the app. Deployed size: 873,472 bytes; SHA-256 `62a14e8e0d9e936644c97c0295921ad6f99eb60678aceec18c5cd7669bd80fb0`. Deployed bytes match the linked file. Existing compiler warnings remain. No tests, UI verification or inference were run; the user verifies the visible result. Projects and credentials were preserved, and temporary build files were removed.
