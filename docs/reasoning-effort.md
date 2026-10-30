# Reasoning effort

The composer places Reasoning effort beside the model picker. Options, labels, descriptions and defaults come from provider metadata. They are not a universal scale or a token/time budget. Only Codex is integrated; no Claude login, runtime or effort mapping has been added.

## Shared adapter contract

`backend/v2/provider_options.py` defines `ProviderOptions`. An adapter supplies its identity, a selected model's `reasoning_effort` presentation, and `turn_options` to translate a validated task snapshot into its own runtime configuration. The presentation contract is:

```json
{
  "state": "supported",
  "options": [{"id": "provider-owned-id", "label": "Provider label", "description": "Provider meaning"}],
  "default_id": "provider-owned-id",
  "message": "Provider-specific explanation"
}
```

`state` is `supported`, `unsupported` or `unavailable`. Missing or malformed metadata is unavailable, not evidence of no effort support. An explicit empty supported-level list is unsupported. A missing/invalid default stays unset; the app does not choose the first option or guess a model-family default. The UI contains no Codex request fields, effort enumerations, numeric rankings or provider mappings. A future adapter must provide its own metadata and mapping; it must not reuse Codex semantics by matching option labels.

The native interface remembers explicit choices in local settings under provider/model keys. A remembered choice is used only while it is in that model's current supported options. Otherwise the reported default is shown and a tooltip explains the fallback. Removed preferences are retained so a temporary catalogue change does not overwrite the user's choice. Disconnected, loading, unsupported, wrong-account catalogue and unavailable states are visible and disabled. Provider-supplied descriptions are available in the menu/tooltips. Model discovery and connection events refresh the control; it does not poll or run inference.

`v2.task` accepts optional generic `provider_id` and `reasoning_effort` (an opaque option ID). Existing callers may omit both. Submission freezes the selected provider/model/effort before image preflight or task execution. The backend validates the selected option against the current account/runtime catalogue; expired metadata is refreshed for explicit choices. A stale, unsupported or invalid explicit option fails before a task/transcript/candidate is created, preserving the draft. It never silently substitutes a different explicit effort.

Tasks retain a `reasoning_effort` snapshot with provider/model IDs, capability state, chosen option ID/label and source (`user`, `provider_default`, or `provider_configuration` when no known override is available). Assistant messages retain the same snapshot. Subsequent UI/model changes cannot rewrite a running task or historical messages. No effort metadata is interpreted as account entitlement.

## Codex mapping

`CodexProviderOptions` normalizes App Server `model/list.supportedReasoningEfforts`, `defaultReasoningEffort` and per-option descriptions. No static model-name or effort-level list is used. Only this adapter maps a captured option ID to `turn/start.effort`. When effort control is unavailable/unsupported or no default is reported and no option was selected, no override is sent; the runtime manages its configuration.

This follows the official [App Server models and turn configuration documentation](https://learn.chatgpt.com/docs/app-server). Effort declarations are cached with the existing account/runtime model catalogue for ten minutes. No extra inference probe, login or billing switch is used.

## Pending validation

No tests or live inference have been authorized for this change. Later focused checks should cover differing model option sets/defaults, missing/empty/malformed declarations, invalid saved preferences, provider/account changes, cache expiry, rejected explicit choices, per-model persistence, submission snapshots through image preflight, runtime mapping on resumed threads and compact keyboard-accessible controls in both themes at Windows scaling. Compilation alone does not verify provider behaviour.
