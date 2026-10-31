# Native UI refinements

The approved OpenDesigner proposal remains the visual direction: quiet engineering workspace, original purple pyramid and Prompt to CAD name, separate project navigation/CAD manager/conversation, neutral layered surfaces, restrained purple actions and cyan CAD selection.

This pass uses the installed Emil design-engineering guidance to refine native controls. It does not introduce a web UI or change project, credential, revision, selection-scope or agent-provider formats. The local proposal remains under ignored tmp/ui-redesign-2026-10-30; no generated exports or downloaded skills are required by the application.

## Before / After / Why

| Before | After | Why |
| --- | --- | --- |
| Global button padding competes with fixed icon sizes | Separate icon/text padding, 16 px icons, explicit disabled icon tint and compact 32/36 px controls | Avoid clipping and make states predictable |
| Blue/teal/gold conventions vary across widgets | Approved shared purple action/link/focus roles, neutral account avatar, cyan CAD highlight | Preserve identity and improve consistency |
| Hover is the main shared interaction cue | Immediate hover, pressed, checked, disabled and reserved-border focus states | Show what can be used without shifting layouts |
| Popovers duplicate screen placement | Shared Qt popup with anchor-screen bounds, Escape and deliberate focus return | Keep controls usable at edges and by keyboard |
| Closed combo can change through type-ahead/wheel | Open an explicit catalogue; arrows/Enter/Space open; search arrows move to results; Enter chooses | Avoid accidental model changes |
| Empty filtered results are unclear | Visible no-match message and accessible names | Explain why a search has no selection |
| Model refresh looks available in disconnected/busy states | Gate settings/menu/popup refresh and prevent disconnected discovery calls | Do not offer an unusable action |
| Notices cover conversation controls and expire while being read | Place over the viewport, pause transient lifetime on hover/focus/inactive app, keep errors dismissible | Keep chat readable and give time to inspect notices |
| Native menu/tooltip effects can delay repeated controls | Disable menu/combo/tooltip fade/slide effects; retain native tooltip timing | Frequent engineering and keyboard actions should be immediate |

## Token mapping

WorkspaceTheme.h/.cpp is the native mapping of the approved token roles. It is source data, not a runtime dependency on ignored design artifacts.

| Role | Light | Dark |
| --- | --- | --- |
| Base | #f7f8fa | #1d1d1d |
| Navigation | #edf0f4 | #151515 |
| Raised / overlay | #ffffff / #ffffff | #252525 / #2d2d2d |
| Canvas | #dce2e9 | #28313a |
| Primary / secondary text | #242424 / #575757 | #e9e9e9 / #ababab |
| Action / on-action | #704094 / #ffffff | #bd80e1 / #151515 |
| Link and focus | #81509d | #cf96f1 |
| CAD selection | #006cab | #59c6ff |

Control/overlay radii remain 8/12 logical px; user bubbles 16. The 14 px default applies only when a saved text-size choice is absent. Existing 12/14 px preferences remain valid; Appearance also offers 16 px. Rich text and icons use the same roles. OpenCascade display changes affect background/highlight presentation, not materials, shape assets or revisions.

The existing panel arrangement and saved geometry are retained. This focused pass does not implement every layout recommendation from the proposal. Full viewport-budget/collapse policy and keyboard splitter controls remain separate work.

Compact controls are desktop pointer targets, not a claim of 44 px touch hitboxes or accessibility certification. Larger text, long labels and DPI still require native review.

## Native behaviour and motion

- Model and effort choices remain provider-owned; no Codex configuration fields are added to shared UI.
- Busy/model-discovery/image-preflight states close the model popups and disable their trigger.
- Escape closes the top popup. An explicit choice or Escape returns focus when the trigger is still usable; opening a successor popup does not steal focus.
- Tooltips retain Qt's native initial/warm timing, without custom hover timers or a new tooltip library. Menu hints include native shortcut text.
- No control scaling, blur, springs, animated panel resizing, stagger or delayed keyboard action is added.
- Transient notices use the approved 4-second lifetime, paused during reading/inactivity; error notices have no auto-dismiss timer.
- Enter/Shift+Enter, IME composition, frozen task selections, per-conversation drafts and attachment submission remain in their existing implementation.

## Source stages and validation boundary

1. Shared palette/control states: WorkspaceTheme, WorkspaceIcons, ConversationView, CadView, startup font default.
2. Popup/keyboard behaviour: WorkspaceControls, WorkspaceChat, account/usage popovers.
3. Connection/settings/notices: WorkspaceSettings, WorkspacePanels and menu wiring.

Only source inspection and diff review were performed. **No tests, builds, app execution, screenshots, installers, authentication or push were performed.** Existing screenshots are design illustrations, not evidence of these native changes. Compilation, runtime behaviour, Windows scaling, focus paths and tooltip timing are pending separately requested validation.

API references consulted: [Qt events](https://doc.qt.io/qt-6/qevent.html), [Qt style hints](https://doc.qt.io/qt-6/qstyle.html), [OCCT 7.8.1 interaction/highlight API](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/AIS/AIS_InteractiveContext.hxx).
