# Current workspace architecture

```text
C++ / Qt CAD workspace
    │ private JSON-RPC process channel
backend.v2.service / WorkspaceV2
    ├── Projects, documents, conversations, tasks and revisions
    ├── Protected ChatGPT / API-key connections
    └── Codex App Server adapter
            │ eight scoped CAD MCP tools
            └── Candidate geometry operations
                    │ private geometry worker
                    └── backend.native
                        CadQuery / OpenCascade solids, recipes and meshes
```

The shared CAD core contains geometry, recipe/schema validation, parameter arithmetic, topology inspection and document storage. It contains no separate HTTP application, custom model provider or legacy chat implementation. The current agent layer owns authentication, App Server streaming/cancellation, task correlation, project/chat persistence, restricted CAD scripts and candidate acceptance.

Tasks freeze revision and explicit selection context. Tools reject stale references and changes outside submitted component scope. Per-document locks and revision comparison serialize geometry writes. Independent validation precedes acceptance; failed/cancelled candidates preserve the accepted revision. Multiple conversations read the actual current document state.

Credentials are protected with Windows DPAPI. The native application owns its backend process tree, the provider owns App Server/tool descendants, and geometry runs in a controlled worker. Internal viewport captures are observations; image generation is not an active workflow. Ordinary modelling uses CAD tools and never modifies application source.

The interface uses one shared dark/light theme for controls and the CAD background. The startup splash owns the logo and an indeterminate animation until the local document service is ready. The native scroll-based chat renderer uses rounded, aligned message widgets with selectable Markdown text. Observable work events expand inline, and completion duration/activity persist on the response. It coalesces streamed text updates and never displays reasoning events. Submitted prompts are removed immediately; later drafts survive task completion. Documented App Server commentary phases are saved as activity, while partial and final answers remain visible. Legacy messages without phase metadata retain their text.

New project collections use named, ignored Projects/ folders and relative document paths. Imported project folders preserve conversation history and start a fresh provider session if the previous runtime is elsewhere. Account credentials are stored separately with Windows protection. Installer inventories are explicit and exclude project and runtime data even when these sit beside the application.

Usage observations are provider-specific: reported allowance windows become remaining percentages with the reported duration/reset, while thread token counts remain separate. The app-owned API-token route can lack allowance reporting; the workspace hides an unreported allowance and uses actual reported token counts when available. Billing management stays in account settings.
