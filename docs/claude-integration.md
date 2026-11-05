# Claude integration

Prompt to CAD can run its CAD agent with Claude as well as Codex. One provider is active at a time, and each keeps its saved connection, so switching back and forth does not require reconnecting.

Claude always runs through the user's installed [Claude Code](https://code.claude.com/docs/en/setup). There are two ways to pay for it.

| Method | Billing | What the app stores |
| --- | --- | --- |
| **Use my Claude Code sign-in** (recommended) | Whatever Claude Code is signed in with: a Claude Pro/Max plan, a Console account, an API key, or a cloud provider | Nothing secret: only a marker that this method is chosen |
| **Anthropic API key** | Per token, to the Anthropic account that owns the key | The key, in the Windows-protected (DPAPI) vault |

## Anthropic's conditions for running Claude Code

This follows Anthropic's [Claude Code legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance), which permits an end user to sign in to the unmodified Claude Code binary with their own Claude subscription. The implementation keeps to its conditions:

- **Unmodified binary.** The app runs the Claude Code the user installed, as published.
- **No credential handling.** Sign-in completes in Claude Code's own flow (`claude auth login` in its own console window). The app never reads `.credentials.json`, never asks for or saves `claude setup-token` tokens, and never offers a Claude.ai login of its own.
- **No restricted sign-in methods.** In sign-in mode the app runs Claude Code with the user's own environment and configuration folder, so every method they set up (subscription, API key, `apiKeyHelper`, Bedrock/Agent Platform/Foundry) keeps working. Only unrelated `OPENAI_*`/`CODEX_*` variables are dropped.
- **Each user pays for their own usage.** The app never pays for, resells or brokers usage.
- **Naming.** The app describes the option in plain text ("Use my Claude Code sign-in") and does not use Anthropic's or Claude Code's names or logos as its own product or feature branding.

Running Claude Code in a product also requires accepting Anthropic's [Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms). Anthropic notes that advertised plan limits assume ordinary, individual use.

## What the user needs

- Claude Code installed on the PC.
- **Sign-in method:** Claude Code signed in. The app's "Sign in to Claude Code…" button opens `claude auth login`, and "Check again" re-reads `claude auth status`.
- **Key method:** an Anthropic API key (`sk-ant-…`) with credits, from the [Claude Console](https://console.anthropic.com/settings/keys).

## Where the user chooses

- **First launch:** a two-slide onboarding. Slide 1 picks Codex or Claude. For Claude, slide 2 offers "Use my Claude Code sign-in" first, with an API key as the alternative.
- **Settings → AI connection:** two provider cards. The Claude panel has a two-way switch between the sign-in and the API key. A card or method with a saved connection switches immediately; otherwise the current provider stays active until the new one connects.
- **Settings → Advanced:** an optional explicit path to the Claude Code executable, plus a runtime check.

## How it works

| Concern | Claude Code sign-in | Anthropic API key |
| --- | --- | --- |
| Sign-in state | `claude auth status` (JSON, exit code), cached 30 s; the app shows only the method and any email it reports | Key validated with `GET /v1/models` (no inference) |
| Environment | The user's own, including `CLAUDE_CONFIG_DIR` and any `ANTHROPIC_*`/`CLAUDE_*` settings | Inherited `ANTHROPIC_*`/`CLAUDE_*` removed; key passed as `ANTHROPIC_API_KEY`; app-owned `CLAUDE_CONFIG_DIR` |
| Models | Claude Code aliases: `sonnet`, `opus`, `haiku` (resolved to the newest model the sign-in can use) | Anthropic `GET /v1/models` |
| Failures | "Not logged in" or "Login expired" → sign in again; plan limits → usage limit | Rejected key, missing credits or rate limits |

**Same in both methods:**
- **Runtime:** `claude -p --input-format stream-json --output-format stream-json`, one process per turn.
- **Tool isolation:** `--tools ""`, `--strict-mcp-config` and `--permission-mode dontAsk`. Only the CAD tools (`mcp__cad__*`) are allowed.
- **Instructions:** passed with `--system-prompt-file`.
- **Sessions:** `--session-id` on the first turn, `--resume` afterwards.
- **Effort:** `--effort`. Low, medium and high for every model; extra high and max also for Opus-class models.
- **Images:** supported.
- **Clarifying questions:** Claude asks them in the conversation.

**Not blocked in sign-in mode:** the user's own Claude Code settings files still load, because `apiKeyHelper` lives there and blocking them would restrict a sign-in method. This means the user's own hooks run, as they would in any Claude Code session.

**Executable discovery:** checks the configured path, `PROMPTCAD_CLAUDE`, `PATH`, `~/.local/bin/claude.exe`, npm's `claude.cmd`, and finally the newest copy the Claude desktop app keeps under `%APPDATA%/Claude/claude-code`. That copy starts signed out when run on its own, so it needs one `claude auth login`. A saved path to an old desktop-app copy falls back to the current one after the app updates. An npm shim is resolved to `node cli.js`, so JSON arguments never pass through `cmd.exe`.

## Verification boundary

Tests cover stream parsing, failure mapping for both methods, environment handling (no credential injected in sign-in mode; the user's own settings kept), `claude auth status` parsing, the sign-in launcher, connection switching and the model lists. They live in `backend/tests/test_v2_claude_provider.py` and `test_v2_claude_code_sign_in.py`. The native smoke check covers both onboarding slides and both Claude methods in Settings.

A live run with a real Claude Code installation, a subscription or a key has not been performed in this change. CLI behaviour follows the published [CLI reference](https://code.claude.com/docs/en/cli-reference).
