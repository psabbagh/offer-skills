# Running the buyers on each host

(The same notes as the startup-buyers skill, whose `buyers.py` this skill runs as an identical copy.)

Each buyer must be a separate run that sees only its own brief. Nothing from this
conversation, and nothing from another buyer, may reach it. That separation is what
makes the panel 100 opinions instead of one opinion repeated.

| host | how to run one wave |
| --- | --- |
| Claude Code | One message with one Agent tool call per buyer (Task in older versions), `subagent_type: general-purpose`. About 10 run at once, so waves of 10. |
| Codex, multi-agent on | Spawn one agent per buyer in the wave with the same one-line prompt, then wait for all of them. |
| Codex, multi-agent off | Ask the user to turn it on (`multi_agent = true` under `[features]` in `~/.codex/config.toml`) and start a new session. Running one `codex exec` per buyer from the shell also works where the sandbox allows network access, but it is slower. |
| Claude Code, from the shell | One `claude -p --model sonnet --allowedTools "Read,Write" --permission-mode acceptEdits "Read <brief path> and do exactly what it says. It is your whole brief."` per buyer, run from the panel folder, 10 at a time (for example with `xargs -P 10`). Each is a separate run that sees only its brief, and none of the 100 answers enters the main conversation. Measured on 2026-11-21: about 15 seconds a buyer, 200 buyers in a few minutes. |
| A chat with no sub-agents | Do not run the panel. Say plainly that one model playing 100 buyers in a single conversation is one opinion, not 100, and suggest Claude Code or Codex. |

The prompt is the same everywhere: `Read <brief path> and do exactly what it says. It
is your whole brief.` After each host's run, `buyers.py check` tells you which
answers are missing.

In Codex, the tool is `scripts/buyers.py` in this skill's folder.

Checked on 2026-11-07: in Claude Code, a 100-buyer run and a 3-buyer run, each buyer
an Agent call; in Codex (CLI 0.147, multi-agent on), a 3-buyer wave, where Codex
spawned one agent per buyer, waited for all three, and each wrote its own valid answer.
