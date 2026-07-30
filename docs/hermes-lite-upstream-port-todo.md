# Hermes-Lite Upstream Port Todo

This tracks upstream Hermes Agent commits worth porting into the trimmed
Hermes-Lite branch.  Port in small batches and verify each batch before touching
the VPS runtime.

## Batch 1 - Compression And Compaction

- [x] `fc2fac73` fix(compressor): prevent orphan user turn after compaction via turn-pair preservation
- [x] `32b23bfb` fix(compressor): strip orphan tool_calls instead of inserting stubs
- [x] `82ac7e16` fix(compression): preserve network/auth abort flags across cooldown re-entry
- [x] `a1a8a967` fix(compaction): place END MARKER last in merge-into-tail summaries
- [x] `b795a45b` fix(compaction): detect and strip merge-into-tail summaries past the delimiter
- [x] `5eaccf58` fix(gateway): queue interrupts during in-flight context compression

Notes:
- The Lite branch already has local compression fixes around transient summary
  failure and structured content. Compare each upstream patch before applying.
- Verified on 2026-07-02 with `python -m pytest
  tests\agent\test_context_compressor.py
  tests\agent\test_compressor_assistant_tail_anchor.py
  tests\gateway\test_compression_interrupt_demotion_56391.py` and `python -m
  py_compile agent\context_compressor.py gateway\run.py`.

## Batch 2 - State DB And Durable Transcript

- [x] `f049227f` fix(state): order conversation replay by id, not timestamp
- [x] `0695a6bc` fix(state): periodically merge FTS5 segments to curb write-lock contention
- [x] `e4c6d1b2` fix(agent): persist messages by intrinsic marker to stop id() reuse data loss
- [x] `59e7e9d0` fix(agent): persist recovered final responses
- [x] `053424c4` fix(agent): preserve final_response on failure returns

Notes:
- These map directly to long-lived VPS stability and trace quality.
- Verified on 2026-07-02 with `python -m pytest
  tests\test_hermes_state.py tests\run_agent\test_identity_flush.py
  tests\agent\test_turn_finalizer_final_response_persistence.py
  tests\run_agent\test_run_agent.py -q -k "final_response or RetryExhaustion
  or invalid_response or identity_flush or conversation_replay or optimize_fts
  or SessionLifecycle or SessionTitleLineage"` and `python -m py_compile
  hermes_state.py run_agent.py agent\turn_finalizer.py
  agent\conversation_loop.py`.

## Batch 3 - Model Routing, Fallback, And Streaming

- [x] `88d1d620` fix(streaming): handle completed responses with empty/None choices
- [x] `a04b7024` fix(error-classifier): route 5xx context-overflow into compression
- [x] `c8376e0d` fix(auxiliary): stop SDK retries from multiplying compression stall
- [x] `88e6f9b9` fix(auxiliary): preserve max_tokens for NVIDIA NIM aux calls
- [x] `fae92064` fix(agent): throttle cross-turn fallback-switch replay storm
- [x] `36bfe3a4` fix(anthropic+feishu): model-gate max_tokens fallback; wire Feishu channel_prompt

Notes:
- Prioritize OpenAI-compatible/newAPI/NIM behavior over desktop or OAuth-only
  provider changes.
- Verified on 2026-07-02 with focused streaming, error-classifier,
  auxiliary-client, fallback-cooldown, Feishu channel-prompt tests, plus
  `python -m py_compile agent\chat_completion_helpers.py
  agent\error_classifier.py agent\auxiliary_client.py
  plugins\platforms\feishu\adapter.py`.

## Batch 4 - Gateway And Subprocess Safety

- [x] `40dbfa0e` fix(gateway): revive gateway on /restart under Restart=on-failure units
- [x] `cc395e80` fix(gateway): close cross-session HERMES_SESSION_* leak into subprocess env
- [x] `daf4f1a7` fix(tools): close same session leak on hermes_subprocess_env spawn surface
- [x] `a658f3b2` fix(security): strip dynamic Hermes secrets from all subprocess spawn env
- [x] `1a0d7878` security(terminal): strip Vertex/GCP credential path envs from subprocess env

Notes:
- Lite is single-profile today, but subprocess env hygiene still matters on a
  VPS with terminal/code execution enabled.
- Verified on 2026-07-02 with focused gateway shutdown/session inheritance,
  local subprocess session leak, dynamic secret, env_passthrough,
  hermes_subprocess_env, codex app-server spawn-env, Docker env, and
  py_compile checks.
- Keep Tirith-related changes out unless explicitly re-enabled.

## Review Checkpoint - 2026-07-05

Last reviewed upstream main: `2ea39daeb` (2026-07-16).

Next review should scan only `2ea39daeb..origin/main`, plus the deferred
watchlist below. Do not re-triage the full fork gap unless the base branch is
rebuilt.

### Batch 5 - Feishu Gateway Stability And Security

- [x] `674e16e7c` fix(redact): stop DB-connstr redaction from corrupting code output
- [x] `c1c179a23` fix(security): redact secrets in background process + foreground env-dump output
- [x] `86e64900b` fix(gateway): preserve sessions across restarts
- [x] `3a83b6bc5` fix(gateway): self-heal stale sessions.json routing at message time
- [x] `d6c53dcdc` fix(gateway): stop per-turn agent-cache eviction from model + message_id signature churn
- [x] `17f07aebd` fix(security): close shell line-continuation bypass in command detection
- [x] `7534b5be2` fix(security): anchor rm hardline rules to command position
- [x] `e7562c394` fix(gateway): skip cross-process guard on session_id switch under same session_key
- [x] `0c0b4b698` fix(security): collapse `$IFS` whitespace obfuscation before approval checks
- [x] `51feecc2b` fix(security): block shell-collapse `rm -rf /` spellings at the hardline floor
- [x] `6a6fd4211` fix(security): block subshell/brace-group wrappers at the hardline floor
- [x] `a1f62f477` fix(gateway): freshness-gate resume_pending against per-message zombies
- [x] `74e59b8b6` fix(security): close abbreviated-flag bypasses in git/sudo approval patterns
- [x] `d5b4879d4` fix(gateway): preserve peer routing across compression recovery
- [x] `00ec3b188` fix(gateway): ignore stale compression session splits
- [x] `201b646d6` fix(gateway): complete on_session_end coverage across all eviction paths
- [x] `485ae54c9` fix(gateway): pass full transcript to compressor instead of filtered messages
- [x] `ebfc49c4d` fix(approval): require exact `./..` segments in the root-collapse hardline token

Notes:
- `c1c179a23` was ported without `infographic/redact-terminal-43025/infographic.png`.
- Already covered before this batch: `36bfe3a44` Feishu channel_prompt and
  `cc395e805` HERMES_SESSION_* subprocess leak.
- Local verification on 2026-07-05:
  - `.venv\Scripts\python.exe -m py_compile gateway/run.py gateway/session.py
    gateway/session_context.py hermes_state.py agent/redact.py
    agent/chat_completion_helpers.py tools/approval.py tools/terminal_tool.py
    tools/process_registry.py tools/environments/local.py
    plugins/platforms/feishu/adapter.py`
  - `python -m pytest tests/agent/test_redact.py tests/tools/test_approval.py
    tests/tools/test_hardline_blocklist.py tests/gateway/test_session.py
    tests/gateway/test_clean_shutdown_marker.py
    tests/gateway/test_session_store_runtime_stale_guard.py
    tests/gateway/test_session_id_cache_coherence.py
    tests/gateway/test_compression_failure_session_sync.py
    tests/gateway/test_session_store_stale_prune.py
    tests/gateway/test_compress_command.py -q` -> 656 passed.
  - `python -m pytest tests/tools/test_process_registry.py::TestHandleProcessRedaction -q` -> 3 passed.
  - `python -m pytest` for the six new fake-runner agent-cache regression
    tests -> 6 passed.
  - Full local Windows pytest was not used as a release gate because
    process/PTTY and AIAgent cache tests depend on Linux-only `os.getpgid` /
    PTY behavior and a single Python environment with both pytest and compiled
    OpenAI/Pydantic wheels.
- VPS deployment verification on `instance-20260413-080555`:
  - `HERMES_HOME=/home/caozuohua99/.hermes-lite
    /home/caozuohua99/.hermes-lite/venv/bin/python -m py_compile ...` passed
    for the runtime files listed above.
  - `tools budget-check --platform feishu --max-tools 999 --json` passed:
    17 tools, within budget.
  - `systemctl restart hermes-lite.service` completed; service status:
    `ActiveState=active`, `SubState=running`, `MainPID=12807`.
  - `gateway.log` confirmed: `[Feishu] Connected in websocket mode (lark)`,
    `✓ feishu connected`, and `Gateway running with 1 platform(s)` at
    2026-07-05 16:37:59 UTC.

### Batch 6 - WAL Safety And Gateway Event-Loop Responsiveness

- [x] `c2a3b9ce5` fix(state): use PASSIVE checkpoint for periodic WAL flush
- [x] `24ea21993` fix(gateway): offload session store calls via asyncio.to_thread
- [x] `94c2a4016` fix(gateway): offload compression-in-flight blocking probes
- [x] `08e9dcf18` fix(gateway): move SessionStore I/O outside its lock

Notes:
- The SessionStore port keeps the Lite JSON routing index and omits full-Hermes
  profile/multiplex helpers. Snapshot persistence uses the existing temp-file,
  fsync, and atomic-replace path.
- `.claude/settings.json` from `94c2a4016` was intentionally omitted because it
  contains upstream developer-machine permissions, not runtime code.
- Local focused verification on 2026-07-16: WAL checkpoint strategy, gateway
  compression-in-flight, and SessionStore lock/I/O tests -> 14 passed.
- VPS pre-deployment state: service active with zero systemd restarts, state.db
  quick-check `ok`; one Lark keepalive timeout was logged and the connection
  subsequently re-established without a service restart.

## Review Checkpoint - 2026-07-29

Last reviewed upstream main: `5c07ba2f3` (2026-07-29).

Next review should scan only `5c07ba2f3..origin/main`, plus the deferred
watchlist below.

### Batch 7 - Safe Updates, Approval Coverage, And Gateway Teardown

- [x] `da26ff986` fix(approval): detect recursive rm when flags follow operands
- [x] `5cc5c58e0` fix(gateway): flush pending memory writes before session teardown
- [x] `41233e19c` fix(gateway): forward failure_reason through the empty-response return path
- [x] `fe8e4d93d` fix(update): make the in-progress marker a cross-process lock
- [x] `37519b4ee` fix(update): use the no-kill pid probe, not os.kill(pid, 0)
- [x] `80d8e41ae` fix(update): publish the cross-process lock atomically (Lite follow-up)

Notes:
- The upstream update marker used a check-then-`write_text()` sequence, so two
  simultaneous processes could still both enter the updater. The Lite
  follow-up writes a complete private payload and atomically publishes it with
  an exclusive hard link. A real two-process regression test proves exactly
  one winner.
- The process-scoped `get_process_hermes_home()` prerequisite was extracted
  from `bf517f930` without importing its unrelated dashboard/theme changes.
- `41233e19c` was adapted to the older Lite gateway fixture while preserving
  the runtime behavior and upstream authorship.
- Local focused verification on 2026-07-29:
  - update lock, including real two-process contention: 17 passed;
  - approval detection: 252 passed;
  - gateway memory flush before teardown: 2 passed;
  - compression/failure metadata session sync: 4 passed.
  - update branch/cache, gateway update streaming, Feishu cards,
    confirmation, and shutdown regressions: 167 passed. Two pre-existing
    Windows test-fixture assumptions were refreshed before the clean rerun.

Deferred:
- `origin/fix/feishu-ws-close-frame` (`1a296b96d`, `91e080583`) remains outside
  upstream main. The observed keepalive timeout does not establish that its
  outbound CLOSE-frame cleanup is the remedy, so keep watching rather than
  importing an unmerged patch.
- `4b039e954` + `bd7938fa0` reconnect-watcher supervision depend on the full
  `_spawn_supervised` task framework that Lite does not currently carry.
  Re-evaluate only with a Lite reproduction or when that framework is ported.
- `58f6678e6`, `40837e2dd`, `23e44a284`, and `72024950c` add a broader shutdown
  recovery-file subsystem. The direct pending-memory drain was ported; keep the
  larger recovery stack deferred until its state-DB prerequisites are audited.

Skipped for Lite:
- Desktop, TUI, MCP, Computer Use, STT/TTS, image/vision, WhatsApp, Discord,
  Telegram, Windows-only, broad provider/platform/product-surface work.

## Not Planned For Lite

- MoA full product surface, `/learn`, `/journey`, Memory Graph, scale-to-zero,
  Slack Block Kit, desktop/TUI UI work, Kanban notifier enhancements, and broad
  Telegram/Discord/Matrix platform work.
