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
