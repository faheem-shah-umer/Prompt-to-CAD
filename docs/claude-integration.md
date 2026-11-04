# Claude integration

Prompt to CAD can run its CAD agent with Claude as well as Codex. One provider is active at a time. Each provider keeps its own saved credential, so switching back and forth does not require reconnecting.

## What the user needs

| Requirement | Why |
| --- | --- |
| An Anthropic API key (`sk-ant-…`) with credits, from the [Claude Console](https://console.anthropic.com/settings/keys) | Claude tasks are billed per token to the Anthropic account that owns the key |
| [Claude Code](https://code.claude.com/docs/en/setup) installed on the PC | The agent loop runs in Claude Code's headless print mode |

Claude.ai Pro/Max subscriptions are not used. Anthropic's terms do not allow third-party products to route requests through a consumer subscription without approval, so the only supported credential is an API key.

## Where the user chooses

- **First launch:** a two-slide onboarding. Slide 1 picks Codex or Claude, and slide 2 shows what that provider needs and connects it. Skipping still marks onboarding as done.
- **Settings → AI connection:** two provider cards. Choosing a card that already has a saved credential switches to it immediately. Choosing one without a credential shows its connection form, and the current provider stays active until the new one connects.
- **Settings → Advanced:** an optional explicit path to the Claude Code executable, plus a runtime check that starts it without using the API key.

## How it works

| Concern | Codex | Claude |
| --- | --- | --- |
| Credential | ChatGPT OAuth or OpenAI key | Anthropic API key, validated with `GET /v1/models` (no inference) |
| Storage | DPAPI vault | Same vault, `mode: "anthropic"` |
| Runtime | `codex app-server` over stdio JSON-RPC, one process per task | `claude -p --input-format stream-json --output-format stream-json`, one process per turn |
| Isolation | App-owned `CODEX_HOME`, shell/web/apps disabled | App-owned `CLAUDE_CONFIG_DIR`, `--tools ""`, `--strict-mcp-config`, `--permission-mode dontAsk`, only `mcp__cad__*` allowed |
| CAD tools | Same stdio MCP server | Same stdio MCP server via `--mcp-config` |
| Conversation continuity | `thread/resume` | `--session-id` on the first turn, `--resume` afterwards |
| Instructions | `developerInstructions` | `--system-prompt-file` (replaces Claude Code's default prompt) |
| Models | Provider catalogue + App Server `model/list` | Anthropic `GET /v1/models` (paginated); image input supported |
| Effort | Reported by App Server | `--effort`: low/medium/high, plus xhigh/max for Opus-class models |
| Usage | Plan allowance windows + tokens | Per-turn token counts summed per conversation; costs in the Claude Console |
| Clarifying questions | Structured `requestUserInput` | Asked in conversation; the user replies in the composer |

The process environment drops inherited `ANTHROPIC_*`, `CLAUDE_*` (except `CLAUDE_CODE_GIT_BASH_PATH`), `OPENAI_*` and `CODEX_*` variables. The API key is passed only as `ANTHROPIC_API_KEY` and is scrubbed from error text.

Executable discovery checks the configured path, `PROMPTCAD_CLAUDE`, `PATH`, `~/.local/bin/claude.exe` and npm's `claude.cmd`. An npm shim is resolved to `node cli.js`, so JSON arguments never pass through `cmd.exe`.

## Verification boundary

The unit tests cover stream parsing, failure mapping, argument and environment isolation, key validation, provider switching and the model catalogue (`backend/tests/test_v2_claude_provider.py`). The native smoke check covers both onboarding slides and the Settings provider cards. A live Claude Code run with a real API key has not been performed in this change. CLI flags follow the published [CLI reference](https://code.claude.com/docs/en/cli-reference).

The Claude effort list is a documented CLI enumeration keyed on model family, not runtime-reported metadata. If Claude Code rejects a level for a model, the task fails with the runtime's message and the draft is kept.
