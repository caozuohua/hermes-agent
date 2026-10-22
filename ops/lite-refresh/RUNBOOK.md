# Lite refresh 2026-10-21

Release branch: `codex/lite-refresh-20261021`, based on live
`8a8833f7d89d523c6f7e43311f31e1e2d9810a65`. No upstream-main merge.

Deployment is now complete at runtime commit `3ef6e1abca6`. See
[RELEASE-REPORT.md](RELEASE-REPORT.md) for the actual cutover, governance,
failed semantic acceptance, full-suite limitations and ongoing observation.
The preparation procedure below is retained for future deployments, not a
claim that the current release is still awaiting cutover.

## Provenance

Selective upstream v0.22.2 ports retain the original authors:
`88704223d2` provider egress redaction, `8079fd01f4` memory write feedback,
`2e4e024ec2` compression refusal rollback, `dda4275846` telemetry preservation,
and `4c7ab8b2a0` trigger/effect telemetry. The last port is partial: newer core
architecture dependencies are excluded. Lite adaptation fixes the pre-commit
memory flush ordering and trigger labels. Telemetry remains local; no new outbound analytics.

## Runtime paths

GCP profile: `/home/caozuohua99/.hermes-lite`; code: `hermes-agent/`;
runtime: `venv/`; session DB: `state.db`; core memory: `memories/`.
Services: `hermes-gateway.service`, `hermes-a2a-bridge.service`.
The real deployment is Python 3.13 and systemd; older debugging skill claims
about a single binary, missing CLI, nohup and workspace/state.db are obsolete.

AWS source: `/opt/mem0`; API deployment: `/opt/mem0/server`;
compose project: `mem0-dev`; history: `server/history/history.db`.
Original runtime/source changes are captured in commit `d299c85`;
bounded dependency policy is `772a268`; pinned image deployment is `40e6b2d`.
Image `mem0-lite:refresh-20261021` has ID
`sha256:de7ed185b8f25299ab784c178494f9d81fb6168f44934a9d553e122d5cff98d9`.
NVIDIA embedding model/vector space, PostgreSQL 17 and API routes are preserved.

## Recovery points and cutover

GCP recovery evidence: `backups/refresh-20261021/` under the profile.
AWS: `/var/backups/vps-sysops/mem0/refresh-20261021/` plus daily PG dumps.
Sensitive archives stay mode 600 inside mode 700 directories and never enter Git.
SQLite uses its backup API. Profile/source archives have been extracted into
temporary directories; SQLite integrity and PostgreSQL temporary restore passed.
AWS dump `mem0_20261022_005336.dump` passed restore-smoke immediately before cutover.

AWS cutover completed in 14.55 seconds. Old GCP client passed isolated real
extraction, list, semantic search and delete probes against the new service.
The extraction probe excluded an assistant's speculative recommendation.
No real personal records were modified by smoke tests.

Before GCP cutover, build a separate locked Python 3.13 environment, run the
Linux release checks, query `gateway.control_socket.query_gateway_control(...,
'status')`, and require `active_agents == 0`. Hold the profile maintenance lock.
Take a fresh backup with `backup_profile.py`, switch code/runtime and config,
then restart only the gateway. Keep the previous directories for rollback.
Cutover budget is 15 minutes. Verify Feishu connected, A2A, process ownership,
500 MiB cap, graceful shutdown, current code SHA and no synthetic credential leak.
Only then disable the existing daily-reboot cron entry and start uptime acceptance.

Rollback restores code/runtime/config first, preserving new state.db, sessions
and Mem0 writes. Governance rollback uses per-record before/after metadata and
core-memory originals. Never overwrite a healthy live database with an old dump.
Full DB recovery is for corruption only, after saving the failure state.

## Memory delivery and QPC

`memory.mem0` in config.yaml controls timeouts, queue bounds and degradation.
The self-hosted plugin persists requests and receipts in `mem0-delivery.db`.
`queued` means definitely unsent. `inflight`, `unknown` and `observed` must never
be blindly replayed. Reconciliation uses request metadata or mutation read-back;
an inferred multi-fact write stays uncertain when only a partial receipt exists.
Unknown requests remain available across restarts; inspect the journal and source
session before manual resolution. Preserve `personal` cross-agent recall scope.

The QPC skill in `qpc/SKILL.md` calls `scripts.qpc_receipt`; its durable intents
live in `qpc-receipts/`. Completion requires API success, record_id and matching
read-back. Timeout retry first looks for an existing record. Never alter table
schema or substitute Mem0 for a QPC receipt. Tests use an isolated HTTP server.

Skills/core memory changes are picked up on new sessions or compression commits.
Do not rewrite persisted system prompts or clear the existing session prefix.
No new core tools or persistent tool-schema framework is introduced.

## Validation and dependency limitations

Linux Python 3.13 focused regression: 629 passed across 63 files, including
compression, refusal rollback, prompt boundary, restart schema equality, logging,
durable HTTP write/restart and QPC receipts. Two existing files timed out once
under parallel load and passed on retry; the report retains both outputs.
A separate stall-fallback test initially failed on both candidate and untouched
baseline, then passed in the wider run. These flakes are not treated as proof of
production failure, and remain tracked validation limitations.

The Windows full-suite run was interrupted after roughly 19k passing tests and
418 failures (platform/optional dependency failures included). It is not a clean
full-suite result; see the retained raw report. Release claims must distinguish
targeted Linux validation from full-suite coverage.

The private fixed recall set contains 20 questions with exported memory IDs,
original text and timestamps. Before governance: 20/20 HTTP successes,
Recall@5 1.00, P95 0.67 seconds. This proves that fixed set, not universal recall.
Another candidate query timed out at 8 seconds, so intermittent external latency
remains real. Component sample: database 0.004s, embedding 0.731s, LLM 2.969s.
Container `/health` explicitly reports semantic dependencies as `not_checked`;
it must not be used as semantic-recall acceptance.

glm-4.5-air returned HTTP 429/code 1113; glm-4.7 succeeded. They share an account
and are not independent disaster recovery. Main Gemini had one HTTP 503 probe;
preserve the configured primary, record subsequent probes, and never auto-top-up.

## Continuous acceptance

Reuse the existing five-minute monitoring cadence. Record timestamp, process
start, service memory/RSS, thread count, restart count, OOM events and connection
state without request content or credentials. After warmup, require comparable
load, memory growth <=10%, service P95 <450 MiB and no sustained thread growth.
72 hours and seven days require actual elapsed observations; never mark them
passed during deployment. Keep daily reboot disabled only while monitoring and
controlled-restart recovery are verified. Escalate meaningful failures, not each
unchanged polling result.
