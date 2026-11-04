# Project turn logs

New AI turns keep diagnostic files **inside the owning project folder**:

```text
<project folder>/
  logs/
    turns/
      <task_id>/
        summary.md
        summary.json
        events.jsonl
```

Open `summary.md` first. It contains the request, timestamps/status, concise stated decisions, phase timings/counters, cq_warehouse counters, final outcome and tool calls. `summary.json` contains structured versions of those fields. `events.jsonl` records timestamped tool starts, bounded arguments/results, errors, phase durations and decision updates as the turn runs. Phase records distinguish provider/AI wait, catalog search/import, geometry-worker time, script execution, assembly verification and final validation; failed attempts are counted without exposing hidden reasoning or source payloads. The corresponding `tasks/<task_id>.json` contains a relative `turn_log` link. The project's folder path is available in the app's project information.

`backend_runtime_verified` and `mcp_tools_delivered` events also identify the loaded source, instruction hash and actual MCP registry. See [runtime consistency](runtime-consistency.md) for diagnosing a source/runtime mismatch. These events distinguish the running contract from whatever files happen to be on disk later.

## Understanding cq_warehouse use

The assistant is instructed to call `cad_decision` after relevant inspection, before modelling and when its approach changes. It reports an approach, supporting facts, alternatives, and a cq_warehouse choice (`use`, `do_not_use`, `not_applicable` or `undecided`) with a short reason. Examples include a matching standard/size, custom geometry outside the catalog, an existing component edit, or a generation failure that changes the approach.

The STEP catalog summary records the availability and fingerprint sent with the turn and whether MCP returned both catalog tools. Search queries, filters, returned metadata and inspection results appear in `events.jsonl`. The summary distinguishes attempted insertions, candidate components, and components retained in the accepted revision. The optional `catalog` decision records the assistant’s stated choice, result IDs and reason separately.

These are **concise assistant-stated explanations**, not hidden reasoning, an exhaustive thought process or proof that an explanation is correct. The application records actual tools independently:

- `discovery_calls`: calls to `cad_standard_parts`. Looking at the catalog does not mean it generated geometry.
- `generation_attempts`: `cad_standard_part` calls, plus numeric parameter regeneration of existing standard parts through `cad_apply`.
- `successful_generation_calls`: those tools returned successfully. A rejected collision or invalid parameter remains a failed attempt.
- `successful_calls_in_accepted_turn`: successful generation calls in a turn with a recorded accepted revision. A cancelled/failed candidate is not silently counted as an accepted design.
- `generator_ids`: the requested/retained generators involved in those attempts.

Compare these observations with the stated decision and the event timeline. The final model can include or derive from standard parts without every component retaining generator metadata. Conversely, a pre-existing standard part alone does not prove this turn used its generator. A successful call followed by a cancelled turn is recorded as successful candidate work without a recorded accepted revision.

If the assistant omits `cad_decision`, the log says `explanation_status: not_provided`. Its final response is retained, but no structured rationale is fabricated from tool absence. Earlier conversations are not retroactively assigned invented reasons. No extra AI request is made just to produce a log.

## Failures, recovery and project copies

Events are flushed during a turn and summaries are updated after calls. On normal failure/cancellation, the log keeps the outcome and any preceding attempts. Startup recovery marks unfinished tasks/calls interrupted where their task record and log are available. An interrupted turn without a recorded result revision has unknown acceptance; inspect document history rather than assuming success or failure. A partial event line from an abrupt shutdown can remain as evidence; later recovery events start on a new line.

Project copies preserve existing logs as historical evidence with their original recorded identities. Copied task records retain relative links to those copied log folders; new turns create new logs. Renaming/moving the project keeps logs with it. Explicit conversation purge removes its app-owned log files along with task records; normal operation does not delete log history.

Logging errors after startup are reported as a logging warning and do not reverse a CAD tool result or silently change geometry. A project that cannot create a new turn log reports a folder-access/free-space error before starting the AI turn. Logs do not replace native project revisions or the conversation.

## Privacy and scope

Logs are private project data, not source code. They contain project descriptions, selected dimensions, tool errors and assistant explanations. The logger excludes provider configuration, account/session fields and raw transport frames; code/image payloads are omitted, source hashes are retained, and known credentials, email addresses and local paths are redacted. Payloads are bounded, with omission markers for large collections.

Redaction cannot guarantee that arbitrary project text contains no sensitive information. Keep logs local and review/redact them before sharing a diagnostic excerpt. `logs/`, JSON/JSONL files and project directories are ignored by Git. Do not commit logs or use private logs as public examples. No tracker, network logging service or automatic upload is added.

Only AI turns use this diagnostic flow; ordinary manual geometry commands do not need an assistant decision. The change is in the Python backend and tool instructions, so restart the app to load it. No native rebuild or new dependency is required.
