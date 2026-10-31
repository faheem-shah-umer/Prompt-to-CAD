# Reasoning effort

The composer shows the selected model and its reasoning effort together in one compact control. Clicking it opens an effort popover; the model name inside opens the searchable model list. Options, labels, descriptions and defaults come from provider metadata. They are not a universal scale or a token/time budget. Only Codex is integrated; no Claude login, runtime or effort mapping has been added.

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

An adapter can request `presentation: "steps"`. Codex uses discrete slider stops in the returned option order; slider positions are local choices for that model, not a shared numeric effort scale. Keyboard arrows move between supported stops. The popover shows the current option's name/description and a reset to the reported default. Providers without this presentation, one-option models and models without a known selected/default option use a discrete list instead. Missing metadata never creates guessed slider levels.

The native interface remembers explicit choices in local settings under provider/model keys. A remembered choice is used only while it is in that model's current supported options. Otherwise the reported default is shown and a tooltip explains the fallback. Removed preferences are retained so a temporary catalogue change does not overwrite the user's choice. Disconnected, loading, unsupported, wrong-account catalogue and unavailable states are visible and effort editing is disabled. Provider-supplied descriptions are available in the menu/tooltips. Model discovery and connection events refresh the control; it does not poll or run inference.

## Automatic model loading

With an existing connected account, the interface schedules one automatic catalogue load after initial state restoration. Sign-in/account/runtime changes schedule the same path. Requests are coalesced with an in-progress discovery and deferred until document work is idle; successful discovery retains the selected model when it is still present. Disconnected launches do not request models or begin authorization. A failed attempt remains visible and offers an explicit refresh without looping on every state refresh/window activation. Stale results from a different connection are discarded. The backend's existing ten-minute metadata cache remains in use; no inference probe or recurring status polling is added.

`v2.task` accepts optional generic `provider_id` and `reasoning_effort` (an opaque option ID). Existing callers may omit both. Submission freezes the selected provider/model/effort before image preflight or task execution. The backend validates the selected option against the current account/runtime catalogue; expired metadata is refreshed for explicit choices. A stale, unsupported or invalid explicit option fails before a task/transcript/candidate is created, preserving the draft. It never silently substitutes a different explicit effort.

Tasks retain a `reasoning_effort` snapshot with provider/model IDs, capability state, chosen option ID/label and source (`user`, `provider_default`, or `provider_configuration` when no known override is available). Assistant messages retain the same snapshot. Subsequent UI/model changes cannot rewrite a running task or historical messages. No effort metadata is interpreted as account entitlement.

## Codex mapping

`CodexProviderOptions` normalizes App Server `model/list.supportedReasoningEfforts`, `defaultReasoningEffort` and per-option descriptions. No static model-name or effort-level list is used. Only this adapter maps a captured option ID to `turn/start.effort`. When effort control is unavailable/unsupported or no default is reported and no option was selected, no override is sent; the runtime manages its configuration.

This follows the official [App Server models and turn configuration documentation](https://learn.chatgpt.com/docs/app-server). Effort declarations are cached with the existing account/runtime model catalogue for ten minutes. No extra inference probe, login or billing switch is used.

## Pending validation

No tests or live inference have been authorized for this change. Later focused checks should cover differing model option sets/defaults, missing/empty/malformed declarations, invalid saved preferences, provider/account changes, cache expiry, rejected explicit choices, per-model persistence, submission snapshots through image preflight, runtime mapping on resumed threads startup request coalescing and reconnect/runtime changes, failure/retry behaviour, combined-trigger layout, discrete slider/reset/model navigation, and keyboard-accessible controls in both themes at Windows scaling. Compilation alone does not verify provider behaviour.
