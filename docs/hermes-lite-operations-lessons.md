# Hermes-Lite Operations Lessons

This note records practical lessons from trimming and running the
`Hermes-Lite` VPS profile on `instance-20260413-080555`.

It is intentionally operational: the goal is to prevent repeated mistakes while
debugging a small VPS gateway, not to describe the full Hermes product.

## Baseline

- Profile home: `/home/caozuohua99/.hermes-lite`
- Service: `hermes-gateway.service`
- Repo checkout: `/home/caozuohua99/.hermes-lite/hermes-agent`
- Gateway platform: Lark/Feishu
- NewAPI endpoint: `http://127.0.0.1:3000/v1`
- Blog workspace: `/var/www/blog`

The stable target is a small model-facing surface:

- default model: OpenRouter `openrouter/owl-alpha`
- fallback/compression: NewAPI `gemini-2.5-flash-lite` with `context_length=65536`
- manual short-context aliases: NewAPI Groq 70B/8B only for short turns
- visible tools: explicit toolsets, with only `web_search` exposed from web
- memory: compact replace-first updates, not unbounded appends

## Debug From The Runtime, Not From Assumptions

Always start from the live process and final model-facing schema.

```bash
systemctl show hermes-gateway.service \
  -p ActiveState -p SubState -p MainPID -p Restart -p NRestarts \
  -p MemoryCurrent -p MemoryPeak --no-pager

journalctl -u hermes-gateway.service -n 160 --no-pager
```

For tools, do not count imported modules. Count what the model actually sees:

```bash
export HERMES_HOME=/home/caozuohua99/.hermes-lite
hermes tools budget-check --platform feishu --max-tools 1
```

For a JSON report suitable for CI or a lightweight deploy check:

```bash
export HERMES_HOME=/home/caozuohua99/.hermes-lite
hermes tools budget-check --platform feishu --max-tools 1 --json
```

The lower-level runtime probe is:

```bash
export HERMES_HOME=/home/caozuohua99/.hermes-lite
set -a
. /home/caozuohua99/.hermes-lite/.env
. /home/caozuohua99/.hermes-lite/.env.lark
set +a
cd /home/caozuohua99/.hermes-lite/hermes-agent

/home/caozuohua99/.hermes-lite/venv/bin/python - <<'PY'
import os, yaml
os.environ["HERMES_HOME"] = "/home/caozuohua99/.hermes-lite"
from model_tools import get_tool_definitions
from hermes_cli.tools_config import _get_platform_tools
cfg = yaml.safe_load(open("/home/caozuohua99/.hermes-lite/config.yaml")) or {}
tools = get_tool_definitions(
    enabled_toolsets=sorted(_get_platform_tools(cfg, "feishu")),
    disabled_toolsets=(cfg.get("agent") or {}).get("disabled_toolsets"),
    quiet_mode=True,
)
names = sorted(t.get("function", {}).get("name") for t in tools if t.get("function"))
print(len(names), names)
PY
```

For skills, distinguish disk, filtered runtime list, and slash resolution:

```bash
find /home/caozuohua99/.hermes-lite/skills -name SKILL.md -type f | wc -l

/home/caozuohua99/.hermes-lite/venv/bin/python - <<'PY'
import os, json
os.environ["HERMES_HOME"] = "/home/caozuohua99/.hermes-lite"
from tools.skills_tool import skills_list
from agent.skill_commands import resolve_skill_command_key
print(len(json.loads(skills_list()).get("skills", [])))
print(resolve_skill_command_key("web_search"))
PY
```

## Path Migration Pitfalls

Moving from `.hermes/` to `.hermes-lite/` is not just changing `HERMES_HOME`.
Common stale locations:

- `.skills_prompt_snapshot.json`
- skill bodies with hard-coded paths
- `config.yaml` and backup-derived config blocks
- systemd `EnvironmentFile` and `Environment=HERMES_HOME`
- workspace scripts and memories

After a path migration:

```bash
grep -RIl '/home/caozuohua99/.hermes/' /home/caozuohua99/.hermes-lite \
  --exclude='*.db' --exclude='*.db-*' --exclude='*.log' 2>/dev/null
```

Clear skill prompt caches after skill/config path changes and restart the
gateway. Long-lived gateway processes keep in-process caches.

## Tool Trimming Lessons

The expensive surface is the tool schema sent to the model. The useful metric is
the final visible tool count, not files under `tools/`.

Avoid enabling a large composite toolset if only one tool is needed. In this
profile, enabling `hermes-cli` plus Tavily credentials made both `web_search`
and `web_extract` visible because `hermes-cli` inherits core tools. To expose
only `web_search`, use explicit toolsets:

```yaml
toolsets:
  - search
  - terminal
  - file
  - code_execution
  - skills
  - memory
  - todo
  - session_search
  - clarify
  - delegation
  - tts
```

Do not rely on `disabled_toolsets: ["web"]` to hide `web_extract` if
`web_search` should remain visible. Disabling the `web` toolset subtracts both.

## Web Search Strategy

Tavily keys live in `.env.lark`, not `.env`. Source both env files when testing
outside systemd.

The cost-aware Tavily policy is:

- simple factual query: `basic`, 3 results, include answer
- latest/news query: `basic`, `topic=news`, `days=7`, up to 5 results
- deep comparison/analysis: `advanced`, up to 5 results
- never request raw content or images from the search tool

This keeps `web_search` useful without reintroducing `web_extract` or spending
free quota on full-text fetches for simple questions.

Provider strategy:

- Keep one model-visible tool: `web_search`
- Use Tavily as the primary high-quality provider while free credits last
- Use Brave Search as the first API-key fallback because its monthly free credit
  is stable enough for light usage
- Keep `ddgs` installed as the final no-key DuckDuckGo fallback for failures or
  empty results
- Use SearXNG only if a reliable self-hosted/public instance is available
- Treat Exa, Parallel, Firecrawl, and xAI as quality/paid or grant-backed
  providers, not guaranteed free daily fallbacks

The search fallback should live behind the same `web_search` tool. Do not add a
second model-visible `duckduckgo_search` tool unless the user explicitly needs
manual backend selection.

## Model And Compression Lessons

Fallback models must be evaluated on context window and TPM behavior, not just
whether they answer and support tool calls.

We hit this chain:

1. OpenRouter had a transient SSE JSON stream error.
2. Hermes fell back to NewAPI `llama-3.3-70b-versatile`.
3. That model had an 8K context and a 12K TPM limit.
4. A 25K request failed with HTTP 413.
5. Compression then failed because Hermes requires a 64K compression model.

Stable rule:

- `fallback_model` should be `newapi-local/gemini-2.5-flash-lite`
- `auxiliary.compression` should explicitly use the same 64K model
- Groq 70B/8B aliases remain manual short-context options only

Do not disable compression to hide this class of failure. Fix the compression
model.

## Systemd Lessons

`Restart=on-failure` does not restart a service that exits via a path systemd
considers successful. Hermes-Lite once exited after `SIGHUP`; systemd recorded
`Result=success` and left it dead.

Use a drop-in:

```ini
[Service]
Restart=always
RestartSec=10s
```

Then verify:

```bash
systemctl show hermes-gateway.service -p Restart -p ActiveState -p SubState -p MainPID
```

Memory limit symptoms must be separated from stop policy symptoms. Check
`MemoryPeak`, `MemoryMax`, and the signal/result before assuming OOM.

## Git And VPS Checkout Lessons

Never run routine git operations as root in the application checkout. A single
root-owned `.git/FETCH_HEAD` can break future fetches:

```text
error: cannot open '.git/FETCH_HEAD': Permission denied
```

Fix only the explicit checkout:

```bash
sudo chown -R caozuohua99:caozuohua99 /home/caozuohua99/.hermes-lite/hermes-agent
```

For the blog repo, keep the remote on SSH. HTTPS push fails in non-interactive
gateway sessions:

```text
fatal: could not read Username for 'https://github.com'
```

Use:

```bash
git remote set-url origin ssh://git@github.com/caozuohua/caozuohua.github.io.git
```

## Skill Lessons

Disk count is not runtime availability:

- `environments: [kanban]` skills are intentionally hidden outside Kanban
- disabled skills do not resolve as slash commands
- skills can be present on disk but not useful if their credentials are absent

Skills modified by a live profile are personal runtime assets unless they live
in the repo. Sync them to the local user skill root or a separate personal
skills repo; do not silently commit them into Hermes core.

Useful profile-local skills from this run:

- `hermes-lite-debugging`
- `hugo-blog`
- `qpc`
- `web_search`
- `feishu-message-formatting`
- `x-ui-and-new-api-security-posture`

## Memory Lessons

Hermes-Lite memory is intentionally small. At around 2.2K chars, append-heavy
behavior starts failing and can distract the agent.

Rules:

- replace or consolidate, do not append
- keep one capability-surface entry, not many dated fragments
- avoid storing verbose logs or counts that change frequently
- when standalone scripts call memory, instantiate `MemoryStore`; the bare
  `memory_tool()` expects an agent-provided store

## Development Workflow

For a change discovered on the VPS:

1. Reproduce and inspect on the VPS.
2. Decide whether it is code, profile config, skill content, or runtime state.
3. Bring code changes back to the local repo.
4. Add the smallest test that protects the behavior.
5. Commit locally and push to a writable fork if upstream is read-only.
6. Cherry-pick or deploy back to the VPS so live code is not dirty.
7. Keep personal profile config and secrets out of the repo.

For this branch, upstream `NousResearch/hermes-agent` is read-only for the
current account. Pushes go to the writable fork remote instead.

## Safe Self-Update Topology

The VPS checkout follows a tested Lite release branch. Keep the Git remotes in
the convention expected by the built-in updater:

```bash
origin    git@github.com:caozuohua/hermes-agent.git
upstream  https://github.com/NousResearch/hermes-agent.git
```

The profile config pins all update surfaces to the Lite branch and requires
confirmation for gateway-triggered updates:

```yaml
updates:
  branch: hermes-lite-local
  require_confirmation: true
  non_interactive_local_changes: stash
```

`/update` therefore fetches and fast-forwards
`origin/hermes-lite-local`, refreshes dependencies, restarts
`hermes-gateway.service`, and reports completion after Feishu reconnects. It
must never target `upstream/main` directly.

Official Hermes commits continue to be reviewed and ported in small tested
batches. Automatically merging the full upstream main branch would reintroduce
the product surfaces removed from Lite and defeats the purpose of this profile.
A documentation-only release-branch commit is the preferred smoke target when
validating the full pull, dependency refresh, restart, and reconnect path.

## Common Misreads

- "No Tavily key" can be wrong if only `.env` was sourced. The service also
  loads `.env.lark`.
- "Websearch works" can mean the helper works, not that the model sees the
  `web_search` tool.
- "Service is fine" can be wrong if `is-failed` is false but the service is
  inactive. Check `ActiveState`.
- "Skill exists" can be wrong for the current runtime if it is disabled or
  environment-filtered.
- "GitHub push failed" may be an auth/remote issue while local build and site
  generation are fine.
