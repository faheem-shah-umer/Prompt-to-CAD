# Approved gallery to native Qt: alignment report

The approved visual target is the local gallery at tmp/ui-redesign-2026-10-30/index.html and its linked static PNG/SVG illustrations. This pass follows that target on ui-redesign, after f5e9abb. The earlier theme, controls and workspace changes are retained.

## Evidence and scope

- **Seen before editing:** the running native dark workspace with a loaded model, CAD manager and empty conversation; the connected AI settings screen. Personal project/account content was not copied into this report or retained as review images.
- **Seen after compilation:** the native dark empty workspace, compact application header/command row, conversation composer and connected settings layout. Opening Settings did not initiate authorization. Cancel dismissed it without changing preferences.
- **Source observations:** light-theme mappings; populated chat and revision cards; working/cancelling controls; disconnected/error settings; responsive layout policy. These are implementation observations, not operated or tested states.
- **Specification metrics:** gallery/QT-MAPPING values such as 44 px header/command area, 48 px rail and panel budgets are logical design/source values. They were not measured from native screenshot pixels.
- No application tests, inference, geometry operations, credential inspection, installer or push were performed. This comparison is **incomplete for runtime visual parity** across every state and display scale.

## Screen-by-screen comparison

All reference filenames below are under the gallery's opendesigner/review/illustrations directory. Shared changes apply to their themed/size variants; synthetic content is not application data.

| Gallery screen | Remaining difference before this pass | Native update and evidence boundary |
| --- | --- | --- |
| workspace-dark-1600.png | Menus, project header and command tabs consumed multiple rows; project actions stacked; visibility used native checkbox cells. | Single application header, 44 px command row with functional group menu, compact project heading action, direct Archive/Trash, visibility eyes, component summary. Dark shell seen after build; populated model tree is source-reviewed only after this pass. |
| workspace-light-1600.png | Shared control hierarchy lacked the gallery's outlined secondary actions and quiet toolbar actions; theme background differed in OCCT. | Same shared structure with light semantic surfaces and component-selection cyan. Theme RGB values are supplied as sRGB for canvas/highlight only. Native light rendering remains unverified. |
| settings-dark.png | Narrow dialog, sidebar on the same surface, Account/Email separate rows, status and disconnect stacked, API disclosure above usage. | Wider resizable native settings dialog, recessed sidebar, Account name/email stack, aligned fields, right-aligned reported status/Disconnect, usage and model-catalogue groups, API disclosure last. Connected dark layout seen after compilation. |
| settings-light.png | Same organization differences; weak distinction between native page and sidebar. | Same layout and existing light palette roles. Light native screen not operated. |
| settings-dark-disconnected.png | Disconnected identity fields occupied space with unavailable values. | Hide connected identity rows when disconnected; keep existing primary registration reconnect, disabled discovery and honest unavailable usage. Source-reviewed; no disconnect performed. |
| settings-light-error.png | No dedicated settings explanation alongside reconnect state; raw workspace registration suffix could appear in ordinary details. | Report actual connection error with warning text and reconnect-needed status; simplify unreported workspace display. Registration identifiers remain in Advanced. Source-reviewed; no revoked-session simulation. |
| workspace-dark-1600-working.png | Composer/header spacing differed; user copy control lived inside the rounded bubble. | Document subtitle, quiet agent settings icon, composer hint and compact model/effort control; copy is below its turn outside the user bubble. Existing observable activity remains attached to its turn. No working task executed. |
| workspace-dark-1600-cancelling.png | Same shared layout differences. | Retain the existing single Send/Stop control and disabled cancellation state; no additional stop button, fabricated progress or hidden reasoning. Cancellation not exercised. |
| workspace-dark-1600-effort.png | Closed model control retained a bordered input appearance and relied on native arrow rendering. | Quiet content-sized model/effort trigger with an explicit adjacent chevron; existing searchable popup, slider, provider-supplied levels and unavailable states retained. Popup behavior not exercised in this pass. |
| control-states-dark.png | All buttons were quiet text; entire tree/list focus rings remained prominent after mouse use. | Distinct outlined secondary actions, quiet icon/toolbar actions, semantic primary actions and keyboard-driven focus cues. Existing immediate hover/pressed/disabled states retained. Full state matrix not operated. |
| control-states-light.png | Same hierarchy and focus differences. | Shared rules with light-mode raised/input surfaces, disabled tint and explicit theme-aware dropdown glyphs. Light state matrix not operated. |
| workspace-dark-1366.png | Extra command/header rows reduced vertical model space; duplicated layout levels. | Compact shell preserves more viewport height. Existing viewport-budget collapse remains; saved preferences are honored. No 1366 px native capture. |
| workspace-light-1366.png | Same sizing differences plus shared light control hierarchy. | Same compact shell/light tokens. No native capture at this size/theme. |
| workspace-dark-1280.png | Same vertical space loss; toolbar group row remained separate. | Single command-group selector plus existing QToolBar overflow; navigation/manager collapse policy retained. No 1280 px native capture. |
| workspace-light-1280.png | Same constrained-layout differences. | Shared compact layout and light surfaces. No native capture at this size/theme. |
| workspace-dark-1920.png | Project title and menus were not in a common application header. | Full-width header with original application name, native menus, centered elided project title and quiet status/history controls. Large dark empty-workspace capture inspected; populated scene parity unverified. |
| workspace-light-1920.png | Same hierarchy difference and theme mapping. | Shared shell and light roles. No native capture at this size/theme. |

## Important implementation details

- Original logo/name, numeric version, file menus and shortcuts remain. Open project is still available through File; the sidebar no longer repeats it as another full-width button.
- Modelling groups are now selected from a native menu in the single command row. All existing Modify, Assembly, Inspect and View actions remain; QToolBar supplies overflow instead of dropping commands.
- The manager's visibility column retains its check-state data, mouse toggles and tool enforcement. Its delegate paints an eye rather than an ambiguous platform checkbox. Assembly grouping rows remain nonselectable geometry.
- Bounds and colours in the manager summary come from actual document metadata. A colour swatch offers editing only for whole-component selection; face/edge scope displays a selection hint instead. Detailed Properties/diagnostics remain available.
- The OpenCascade theme fix changes only canvas/highlight colour interpretation, not stored component colours, assets, materials, transforms or revisions.
- Drafts, Markdown, attachments, task selection snapshots, model/effort mapping, account/session reuse and project/conversation storage paths are unchanged.
- Authentication/error/usage labels use existing reported state. No sample account, token balance, model capability or validation result from the gallery is hard-coded into runtime state.
- A separate read-only source review found an icon-padding issue and a face-selection colour-link mismatch; both were corrected. It did not verify rendered parity or interactions.

## Deliberate native adaptations and remaining differences

1. Windows keeps its native window title bar; the gallery does not illustrate this system chrome. Settings remains a resizable native dialog with explicit Save/Cancel, rather than a full-window web overlay. Small screens may scroll settings content.
2. Existing saved compact text size and panel widths/visibility are honored. The gallery's body default is 14 logical px; the existing Compact (12), Standard (14) and Larger (16) settings remain available. No personal preference is silently reset to make a screenshot resemble the illustration.
3. The synthetic exploded enclosure, selected cover, account identity, messages, attachments and usage are illustrative. Real CAD placement, colours, conversation content and reported provider state drive the native UI. No automatic explode/recolour or fabricated task result is added.
4. Document tabs retain their supported switching behavior. The gallery's tab-close glyph is not added because document closing is not an existing supported workspace command. Existing revision links retain restore behavior rather than pretending to open a new revision browser.
5. The gallery's small selection label floating on the model is represented by existing viewport highlighting and the removable composer selection context. A new CAD overlay was not introduced over the native OpenCascade surface.
6. Loaded geometry, light rendering, keyboard paths, resized panels, Windows scaling, live provider errors, streaming, cancellation and CAD revisions remain unverified after these changes. Static mockups and source inspection are not evidence that those interactions work.

## Build and launch

The native build succeeded using the existing isolated MSVC/Qt/OCCT 7.8.1 toolchain. Generated output stays in the sibling Prompt-to-CAD-build directory. The existing Prompt to CAD.lnk → Prompt to CAD.vbs launcher still targets that directory's bin/PromptToCAD.exe; no new installer or shortcut is required. Build warnings include optional Vulkan headers absent, the vendor OCCT CMake warning and existing deprecated-action/shadow warnings.

Only reviewed source, original glyphs and documentation belong in Git. The gallery, toolchain, executable, personal content and review output remain outside tracked source.

## Owner refinements — 31 October 2026

The subsequent requested refinements supersede the corresponding gallery details: File/Edit/View/Tools/Help start at the left of the application header, with Prompt to CAD centered and project/document naming retained in the existing document tabs and Windows title. All four command groups are visible tabs in the compact command row. Archive and Trash are icon-only rail controls above Settings/account, with tooltips and accessible names. Advanced registration removal uses the same application trash glyph. The account button paints a circular face directly so its initials do not depend on platform rectangular button styling. Existing account, project, conversation and CAD handlers remain unchanged.
