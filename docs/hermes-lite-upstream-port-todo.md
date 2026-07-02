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

## Not Planned For Lite

- MoA full product surface, `/learn`, `/journey`, Memory Graph, scale-to-zero,
  Slack Block Kit, desktop/TUI UI work, Kanban notifier enhancements, and broad
  Telegram/Discord/Matrix platform work.
