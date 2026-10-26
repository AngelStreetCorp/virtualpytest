# Clash of Clans played by an AI (game_clashofclans_llm)

The script `game_clashofclans_llm` plays Clash of Clans on a phone by looking at the screen. At each
step, a vision model (Claude Haiku 5.5) sees the real screenshot and chooses one tap, swipe or wait.
The run report has one row per step: what the model saw, what it said, what it did, and the tokens
and cost. It also has the full video of the run.

## Run it

Pick the script in **Run Tests**, choose the phone as the device, and set its four arguments:

- **mode**: `play` (the default) collects, upgrades, trains and attacks, then ends when there is
  nothing useful left to do. `tutorial` finishes a fresh account.
- **Steps**: how many model steps this run may take. At most 300. The default is 60.
- **Run budget**: the most dollars this run may spend. At most $0.25. The default is $0.05.
- **Monthly cap**: the API limit per calendar month for this game on this host. You can lower it,
  but never raise it above $50. The default is $50.

<div data-technical>

| Argument | Default | Meaning |
|---|---|---|
| `mode` | `play` | `play`: collect, upgrade, train, attack, then end when there is nothing useful to do. `tutorial`: finish a fresh account |
| `max_steps` | 60 | most model steps in this run (at most 300) |
| `run_budget_usd` | 0.05 | most dollars this run may spend (at most $0.25) |
| `monthly_cap_usd` | 50 | API cap per calendar month for this game on this host (can be lowered, never above $50) |

</div>

## It cannot overspend

The script refuses to start when the month's or today's allowance is spent. During a run, it stops
before any step that could go over the run budget. The report shows what has been spent and what is
left.

## Schedule it

The game is turn-based. Buildings, troops and collectors work on timers. So run it **every hour**.
A run that finds nothing to do ends after two steps and costs a fraction of a cent.

<div data-technical>

Deployments, cron `0 * * * *`, parameters `--mode play --max_steps 60 --run_budget_usd 0.05`.

</div>

Model calls go through the AI settings. Check two things before you schedule it:

- The usage `vision.game_coc` must be sent to a `claude-haiku-5-5` profile.
- That model must have a price above zero in the prices list, or the run is refused.

<div data-technical>

Settings → AI: route `vision.game_coc` to a `claude-haiku-5-5` profile. The model's price row
(Settings → AI → Prices) must exist and be above zero.

</div>

The report links the full video of the run.
