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

## Provider-owned reasoning effort — 2026-10-30

Added a compact selector beside the model picker, provider/model preferences, explicit capability states and frozen task/assistant effort metadata. The shared presentation/validation contract is independent of Codex request fields; Codex owns its catalogue normalization and turn configuration mapping. See [the effort contract and pending validation](reasoning-effort.md). Claude remains deferred.

The Release build completed successfully after correcting a missing native include, with existing SDK/Qt and variable-shadowing warnings. The executable behind the existing shortcut was replaced after the user closed the app. Deployed size: 886,272 bytes; SHA-256 `cfd45adf6c679c65a934c55a32062b4a24b18d8b87d04db78e802a56670424dd`. Deployed bytes match the linked file. No tests, live inference, account authorization or UI verification were performed. Projects, credentials and existing drafts were not edited during implementation. Temporary compiler/SDK/build files were removed after deployment.

## Automatic model loading and combined effort popover — 2026-10-30

Connected launches now schedule one coalesced model-discovery attempt after initial state restoration. Account/runtime changes use the same deferred path; repeated state/window updates do not repeat an attempted discovery. Disconnected launches do not initiate authorization or inference. Failed requests retain explicit refresh, and results for a different connection are discarded.

The composer renders model and effort in one compact trigger. Its popover offers provider-reported discrete slider stops, current-level text/description, provider-default reset and a model link to the existing searchable picker. Other provider presentations/unknown defaults use a discrete list. Preferences, task snapshots, unsupported/unavailable states, keyboard access and both themes remain supported in source; behaviour validation is pending.

All 21 Release build steps completed successfully with existing warnings. The existing shortcut now uses the new executable: 906,752 bytes; SHA-256 `f7e40f252b60fad868ae96765dc693177a4d364b1472ac8639da70d8bbb63df1`. Deployed bytes match the linked file. No tests, UI verification, live model requests or account authorization were run. Projects and credentials were preserved. Temporary compiler/SDK/build files were removed after deployment.

## Expanded Working panel flicker fix — 2026-11-01

Live assistant updates now retain the existing conversation widgets. Elapsed time, activity, phase and streamed reply text update in place, and unchanged labels/Markdown are left alone. Empty live replies retain hidden text/copy controls so the first streamed text does not require replacing the history; Copy reads the current reply. Structural or theme changes still rebuild the conversation. Replacement contents are parented to the scroll viewport, and `setWidget` disposes of the previous contents directly instead of detaching them with `takeWidget`, avoiding a transient top-level native widget.

The explicitly requested Release build completed all 21 compile/link steps with existing compiler/SDK warnings. The launcher's actual target is the sibling `../Prompt-to-CAD-build/bin/PromptToCAD.exe`, which now contains this fix: 1,046,016 bytes; SHA-256 `139bc83b66659da5040879f360331167ab34c908d3cc83ac773f9aa7069cc654`. The launcher and shortcut were retained. The existing sibling toolchain and build directory were reused; no SDK downloads or installer were needed.

`git diff --check` passed. No automated/UI tests, live inference or account authorization were run; visible flicker during an actual streamed task remains to be confirmed. Project and account data were not edited.

## Delayed background-loading indicators — 2026-11-01

Added a small native spinner with an operation label for background workspace requests, model discovery and reference-image preparation. Requests completing before the 200 ms delay show no indicator. Conversation loading uses a badge inside the chat viewport; project/document and other workspace operations use the status bar. Completion/failure cancels the delay and hides the indicator immediately. Agent generation continues to use the existing Working activity UI.

The spinner uses the existing startup animation's 1,050 ms linear cycle and theme colors. Frames invalidate only the icon rectangle without rebuilding the conversation or changing layout. Hidden indicators stop their animation timers. Windows' client-area animation preference selects a static ring, with the loading label still visible, when animations are disabled. The implementation follows the local animate and animation-performance skills, adapted to native Qt painting.

The Release build compiled and linked successfully using the existing sibling toolchain and build directory. The launcher's target `../Prompt-to-CAD-build/bin/PromptToCAD.exe` is updated: 1,055,744 bytes; SHA-256 `a650553262dd6758600d8f6f69ad61b87d3df536551a059fc0a6d01a31ab2ca7`. Existing SDK/Qt deprecation and shadowing warnings remain. No new SDKs, installer or launcher changes were needed.

`git diff --check` passed. No automated/UI tests, live inference or account authorization were run. Delayed appearance, cancellation/error cleanup, dark/light appearance, reduced-motion behavior and perceived smoothness remain to be checked in the running app. Project and account data were not edited.

## Accidental desktop windows during chat rendering — 2026-11-01

The earlier flicker update retained widgets during streaming, but did not fix controls being shown before they had a parent. Expanded activity labels used `setVisible(true)` while unparented; reply/copy initialization also did this. Qt treats an unparented widget as an independent window, then hides/reparents it when the layout adopts it. This explains the brief app-icon/title-bar windows in the supplied screenshots; they are not the loading indicator. See the [Qt 6.9 ownership and visibility contract](https://doc.qt.io/archives/qt-6.9/qwidget.html#QWidget).

Every chat row, turn, bubble and control now receives its intended parent in its constructor, before any visibility changes. `MessageText` requires a parent. The same early-visibility defect was corrected for the model-picker empty label and the Settings API section. Loading indicators remain embedded children with no independent window flags.

The changed sources compiled and the Release executable linked successfully, with existing warnings. The existing launcher's target `../Prompt-to-CAD-build/bin/PromptToCAD.exe` is updated: 1,056,256 bytes; SHA-256 `c76ffad7036bd9317278ca68644d70c5487b37252ffa9e529f3d4b998d7f0ac6`. `git diff --check` passed. No automated/UI tests, live inference or account authorization were run; visible confirmation in the running app remains pending. Project and account data were not edited.
