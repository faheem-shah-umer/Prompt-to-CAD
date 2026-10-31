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

The approved three-pane arrangement and existing saved geometry are retained. The 48 px rail controls navigation, CAD manager and conversation independently. Preferred widths (224/232/384 px initially) are stored separately from temporary collapse: narrowing the window hides navigation and then the manager before reducing the viewport from a preferred 640 px to a compact 480 px. Explicitly opening a pane gives it priority. Chat remains at least 320 px when shown. Splitter handles have an 8 px pointer target and keyboard arrows resize in 16 px steps. These are logical layout budgets, not verified guarantees for every DPI or text size.

Compact controls are desktop pointer targets, not a claim of 44 px touch hitboxes or accessibility certification. Larger text, long labels and DPI still require native review.

## Native behaviour and motion

- Model and effort choices remain provider-owned; no Codex configuration fields are added to shared UI.
- Busy/model-discovery/image-preflight states close the model popups and disable their trigger.
- Escape closes the top popup. An explicit choice or Escape returns focus when the trigger is still usable; opening a successor popup does not steal focus.
- Tooltips retain Qt's native initial/warm timing, without custom hover timers or a new tooltip library. Menu hints include native shortcut text.
- No control scaling, blur, springs, animated panel resizing, stagger or delayed keyboard action is added.
- Transient notices use the approved 4-second lifetime, paused during reading/inactivity; error notices have no auto-dismiss timer.
- Enter/Shift+Enter, IME composition, frozen task selections, per-conversation drafts and attachment submission remain in their existing implementation.

## Completed implementation areas

The earlier theme/control and popup/connection commits are preserved. This pass extends their native widgets rather than replacing the design system.

1. **Theme and controls:** semantic light/dark palette, immediate enabled/hover/pressed/checked/disabled/focus states, shared popup behavior, authored CAD command glyphs and original branding.
2. **Shell and viewport:** elided project title with full tooltip, document tabs, checked rail/menu panel controls, persistent pane preferences and keyboard-resizable splitters. The original command groups and supported operations remain.
3. **Conversation:** unboxed assistant text, rounded user bubbles, accessible collapsed task history, human-readable component links and change summaries. Validation text uses only retained reported fields. Existing drafts, Markdown, attachments, task snapshots, copy, scroll-follow and provider-owned model/effort behavior remain.
4. **CAD manager:** nonselectable assembly groups, separate visibility column, filtering and geometry selection, human-readable Properties with reported dimensions/units, named parameters and engineering records. Raw identifiers and JSON remain behind explicit technical diagnostics. Revision lists show summaries rather than hashes; restoring retains existing behavior.
5. **Connection and notices:** distinct reported account/workspace/billing rows, aligned reported usage, catalogue discovery state, folded separately billed API access and advanced registration cleanup. Existing account storage/reuse is unchanged. Notices remain outside chat; concise summaries retain full diagnostics, and error lifetime remains persistent until dismissal.

## Delivery and verification boundary

The native executable was compiled using the isolated MSVC 14.40.33807 toolchain and exact OpenCascade 7.8.1 SDK outside the checkout. Build output and runtime dependencies are in the sibling Prompt-to-CAD-build directory. The existing VBS/shortcut opens that executable; no installer is generated.

The requested native launch inspection confirmed an empty workspace and the updated conversation panel. It did not open project content, authenticate, initiate inference or perform CAD operations. This is a launch observation, not automated acceptance testing. Prior proposal images remain design illustrations, not screenshots of the native implementation.

No application tests were run. Dark/light interaction matrices, laptop/narrow layouts, Windows scaling, screen-reader paths, loaded-model properties, provider flows and task execution remain unverified at runtime. A requested independent source review could not complete because the reviewer agent reached its usage limit; it is not counted as a passed review. Build diagnostics include optional Vulkan headers absent and existing deprecated-action/shadow warnings.

API references consulted: [Qt events](https://doc.qt.io/qt-6/qevent.html), [Qt style hints](https://doc.qt.io/qt-6/qstyle.html), [OCCT 7.8.1 interaction/highlight API](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/AIS/AIS_InteractiveContext.hxx).

## Gallery alignment follow-up

The linked static gallery is the approved visual target. The subsequent native pass consolidates application menus/title into one header, uses a single command row, refines manager visibility/summary, separates button roles, and aligns settings organization more closely. See [screen-by-screen alignment and remaining differences](ui-gallery-alignment.md). The gallery remains static reference material; neither it nor this source report proves unoperated states.
