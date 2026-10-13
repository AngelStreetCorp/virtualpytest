# Token usage — what's burning and why

> Live analysis of the per-session token ledger. Written by mm-manager on
> 2026-10-10 07:09Z in response to the owner's "is this normal?" question
> about the 145M-token / 24h top-line. Re-run the analysis any time with
> `python3 /tmp/mm-token-analysis.py` (the script lives in `/tmp/` and
> reads the same ledger + summary the dashboard reads).

**Related docs**
- `docs/agent/ai/langfuse_integration.md` — how the tailer is wired (the
  "what" — this doc is the "what does it look like in practice").
- `ghosty-sessions/usage/prices.json` — per-model USD rates. The
  `PLACEHOLDER yyyy-mm-dd:` rows in `source` are the ones an agent shipped
  without a real price; owner can `grep PLACEHOLDER` to find and replace.

## TL;DR

**548M tokens in the last 24h, 93.8% minimax, 6.2% codex, 0% claude
(that last one is a gap to fix — see §5).** That headline number looks
alarming until you split it: **96–99% of every top-5 session's tokens
are `cache_read`, not new input or output.** The actual *new* work
(input + output, the only part that maps to cost) for the top 5 is
**~9M tokens total in 24h** — three orders of magnitude less than the
headline. Cache_read is the agent re-reading its own system prompt +
recent files repeatedly; that's the point of the cache.

The two real things worth a look:

1. **TASK79-stream-latency-codex** burned **27.45M tok/h for 1.2h** on
   `gpt-6-luna` (mostly cache_read) — the Codex session actively
   investigating HLS routing. That's 3× the next-highest burn rate. Not
   a leak — it was a focused investigation that ended — but it's the
   only outlier on rate.
2. **The "claude" agent is missing from the 24h rollup.** We know
   claude-sonnet-5-5 / claude-opus-5-5 are being used (the 14d summary
   shows them at $49 + $18 + $12 + $6 cost) but no claude records have
   a `ts` in the last 24h. Either the active Claude sessions are all
   paused, or the Claude Code transcripts haven't been written yet. See
   §5 for the verification steps.

## 1. Methodology

| Source | What it tells you | Granularity |
|---|---|---|
| `usage-ledger.jsonl` | one record per assistant turn, full usage numbers | per-turn, per-session |
| `usage-summary.json` | rollup (per-agent / per-session / per-day / per-model) | 14d window, 5-min slot resolution |
| Langfuse `codebox-usage` project | cloud mirror of the ledger | same per-turn, plus scores / dataset |

The 24h numbers in this doc come from a fresh scan of the ledger
(`python3 /tmp/mm-token-analysis.py`), not the summary file, because
the summary is a 14d rollup and its "today" is the UTC day which is
only 7h deep right now. The ledger is the source of truth for the
last-24h view.

## 2. Top 5 consumers (last 24h, rolling)

| # | session | 24h tokens | turns | input | output | cache_read | cache_write | span | rate |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | TASK79-stream-latency (minimax) | 145 528 776 | 637 | 1.18M | 128K | 144.22M | 0 | 13.5h | 10.77M tok/h |
| 2 | ghosty-quickfix-codebox (minimax) | 123 836 801 | 835 | 2.05M | 356K | 121.43M | 0 | 12.4h | 10.00M tok/h |
| 3 | TASK32-Drone (minimax+manager) | 112 243 051 | 479 | 1.47M | 261K | 110.52M | 0 | 10.5h | 10.72M tok/h |
| 4 | mm-manager (minimax+manager) | 79 740 400 | 375 | 2.59M | 263K | 76.88M | 0 | 22.0h | 3.63M tok/h |
| 5 | TASK79-stream-latency-codex (codex) | 33 124 493 | 277 | 690K | 87K | 32.35M | 0 | 1.2h | **27.45M tok/h** |

(Sorted by 24h tokens, descending. `cache_write` is zero everywhere in
the last 24h — the system is reading the cache, not warming it.)

What each one was doing, briefly:

- **#1 TASK79-stream-latency (minimax)** — the HLS / WebRTC routing
  investigation on the Pi. 13.5h of steady work, 637 turns. Cache
  ratio 99% means almost every turn re-reads the same large context
  (the Pi's `output.m3u8` segment list, prior turns, the task MD).
- **#2 ghosty-quickfix-codebox (minimax)** — the session that shipped
  QF-01…QF-14 (focus lock, picker search, swipe feedback, ask-popup
  pill, etc.) plus the in-flight QF-15/16 paperwork pass. 835 turns is
  high but expected for a long QF batch. 346 of those turns are
  subagent invocations (per the `subagent: true` flag in the ledger).
- **#3 TASK32-Drone (minimax + 12 manager rows)** — the Tello drone
  integration. Standing-by on vpt-pi4 since 20:25Z yesterday (battery
  19% at last check). The 12 `manager` rows are the AI reviewer's
  Jev-decision lines for the `[asks]` events; the rest is minimax.
- **#4 mm-manager (minimax + 1 manager row)** — this session. 22h
  span because the session has been alive since 09:11Z yesterday. The
  burn rate (3.63M tok/h) is the lowest of the top 4 *and* the longest
  span, so cumulative tokens are smaller than the focused work
  sessions. The 1 `manager` row is the Jev probe.
- **#5 TASK79-stream-latency-codex (codex)** — the Codex session that
  is the same investigation as #1, but a different session on a
  different model (`gpt-6-luna`). It only ran for 1.2h but at 27.45M
  tok/h, the highest rate on the board. Looking at the run window
  (21:20Z–22:32Z) this is the burst that did the actual probes
  (`/hot/...` vs `/segments/...` routing). It ended; not a leak.

## 3. The cache_read dominance — why 99% is good news

For every top-5 session, the split is roughly:

```
input       0.8 – 1.6 %   (the actual new tokens the model had to read fresh)
output      0.07 – 0.3 %  (the actual new tokens the model wrote back)
cache_read 96 – 99 %      (tokens the cache already had, billed at the cache rate)
cache_write 0 %           (no cache warming in the window)
```

`cache_read` is the cheapest category (1/10th to 1/40th the input
rate, depending on model — `MiniMax-M3` is currently `PLACEHOLDER` $0
so we can't see the exact cost yet, but the *ratio* tells the story
either way). When the tailer sees 99% cache_read, the agent is doing
the right thing: re-using context instead of paying for it again. The
"huge" token counts are the cache doing its job.

A real leak would look like:
- `input` dominating (>50% of total) — the agent is re-sending the
  same context without a cache hit. That would be a prompt-cache
  misconfiguration, not a burn issue.
- `output` dominating — the agent is writing huge responses. That
  would be a verbosity bug.

Neither pattern shows up in the top 5.

## 4. Anomalies and things to watch

| Item | Status | Action |
|---|---|---|
| TASK79-codex 27.45M tok/h burst | One-off, ended 22:32Z yesterday | None — was a focused probe run |
| ghosty-quickfix 346 subagent turns / 835 | High but expected for a long QF batch | None |
| mm-manager 22h span, 3.63M tok/h | Lowest rate in the top 4; longest span | This session is the right shape, not a leak. Recommend `/compact` after this turn to keep the per-wake re-read cost down. |
| `cache_write = 0` across the top 5 | No cache warming in the window | Means the system prompt is stable; no session is changing it. If a future session starts doing large `cache_write`, that means a long file or tool result is being primed — worth a glance. |
| `MiniMax-M3` price = `PLACEHOLDER` | All minimax cost reads $0 (honest) | Owner: replace with real numbers when known. The cost column will start populating immediately on the next restart. |
| `gpt-6-luna` / `gpt-6-sol` price = `PLACEHOLDER` | Same as above for Codex | Same — owner to set. |
| Codex 5h at 99–100% (3 events) | P0 in the quota rules, already alerted | No re-alert. The 100% peak in this window is the same burst as the 27M tok/h spike above; correlation is direct. |
| `openai/gpt-4.1-mini` and `typesafe/jev-1.13` (50 + 18 turns) | Not in `prices.json` | These use a different format (`provider/model`) and may be priced by a separate code path. If the cost column reads $0 for them, look at the manager's parse rule. Low priority. |

## 5. The Claude gap — investigation

The 24h ledger has **0 claude turns** even though the 14d summary shows
claude-sonnet-5-5 (573 turns) and claude-opus-5-5 (209 turns) as the
biggest *cost* contributors. That means the active Claude sessions
have all gone idle in the last 24h, or the `.jsonl` transcripts in
`~/.claude/projects/` haven't been written/touched. To verify:

```bash
# 1. Are any Claude sessions alive right now?
tmux list-sessions | grep -E '^(claude|.*-claude|.*-review|.*-editor|.*-planner)'

# 2. Have the transcript files been modified in the last 24h?
find ~/.claude/projects -name '*.jsonl' -mmin -$((24*60)) 2>/dev/null | head

# 3. Is the tailer actually tailing them?
journalctl -u ghosty-usage --since '24 hours ago' | grep -c '"agent":"claude"'
```

If (1) is empty and (2) is empty, this is expected — the 14d
summary's claude totals are from sessions that were parked. If (1) or
(2) shows live activity but the 24h ledger is empty, the tailer
offsets may be stuck or the read path is broken; the per-agent
visibility fix (adding the missing models to `prices.json`) won't
help, that'd be a separate bug.

## 6. Action items

In order of how much they'd move the needle:

1. **Owner: set real prices for `MiniMax-M3`, `gpt-6-luna`, `gpt-6-sol`**
   in `ghosty-sessions/usage/prices.json`. The `PLACEHOLDER` rows are
   shipped per the fix-it-yourself policy; `grep PLACEHOLDER` to find
   them. Once real prices land, the per-session `cost` and `today.rate`
   columns populate on the next `ghosty-usage` restart.
2. **Verify the Claude gap** with the three commands in §5. If the
   tailer is missing live claude turns, that's a separate fix to
   investigate (probably offsets or a directory mismatch).
3. **Consider a `cache_read` budget per session.** The current
   96–99% ratio is fine, but if any single session creeps past 30
   turns/hour with cache_read > 100M, that's a candidate for a prompt
   audit (the system prompt or the recurring file loads are getting
   too big). Not urgent today; flag it as a follow-up.

## 7. Re-running the analysis

The script reads the ledger and the summary on every run, so the
numbers above are accurate as of 2026-10-10 07:09Z. To refresh:

```bash
python3 /tmp/mm-token-analysis.py
```

To re-run from scratch with a different window (e.g. last 6h), edit
the `since_24h` line in the script and replace it with `now_ms - 6 *
3600 * 1000`. The script is intentionally throwaway — it lives in
`/tmp/`, not in the repo, because the data shape is going to evolve
as more agents/models land and the static script would go stale.
