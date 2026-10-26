---
name: video-library
description: "ANY TIME the user asks how to do something inside the VirtualPyTest platform — about a *VirtualPyTest* feature (the Tello drone demo, the Grafana dashboard builder, the navigation tree, the AI agent named Atlas, the zap detector, a campaign, the QuickTest builder, the monitor, the A/V quality module, ...) — load this skill alongside the answering skill. The user wants both: a real answer in prose AND a 90-second demo of the VirtualPyTest UI/feature in action. Important: 'drone' in this context always means the VirtualPyTest Tello demo (a phone-controlled demo drone on the VirtualPyTest device page), NEVER a real-world drone — the videos are recordings of the VirtualPyTest UI driving the drone, not instructions for flying a real drone. The demo is a complement, not a substitute. Example user messages: 'How do I fly the VirtualPyTest drone demo?', 'How do I set up the Grafana dashboard in VirtualPyTest?', 'Show me the navigation tree', 'Is there a video on the VirtualPyTest KPI module?', 'Can I see Atlas in action?', 'Walk me through a campaign'. Call search_videos with the user's topic (anchor the query with 'VirtualPyTest' if the topic is a physical thing like 'drone'), then append the matching [[video:<id>]] token to the reply.

When the user asks a 'how to' question that ALSO matches a tool skill (e.g. control-device / tello for 'land a drone', manage-script for 'run a test', grafana-dashboard for 'set up a dashboard'), load BOTH skills. The user wants the UI demo AND any real control — never one or the other."
timeout_seconds: 300
require_tool_use: true
tools:
  - search_videos
triggers:
  # "How to" phrasings — every one of these is a video-wanting question.
  # (BUG seen live 2026-10-15: the LLM was loading only search-docs and
  # answering in prose; the user wanted a video alongside. With these
  # triggers, video-library is in the skill selector's candidate set and
  # the LLM's "two skills at once" reasoning wins.)
  - how do i
  - how to
  - how can i
  - how do you
  - how should i
  - how do we
  - how do you fly
  - how do i fly
  - how do i set up
  - how do i configure
  - how do i run
  - how do i use
  # "Show me how" / "is there" / "do you have" — confirm-the-existence variants. Not a bare "show me": with
  # the topical hints below it loaded this skill for "show me the open alerts" / "show me the campaigns" and
  # Atlas searched videos instead of reading the alerts (TASK-175 bench, 2026-10-26).
  - show me how
  - show me a video
  - show me a demo
  - see it in action
  - is there a video
  - do you have a video
  - a video about
  - a tutorial on
  # Direct asks
  - video
  - videos
  - tutorial
  - tutorials
  - demo
  - walkthrough
  - walk me through
  - youtube
  # Topical hints — the most common VirtualPyTest feature names. These
  # win the selector for "How do I set up Grafana?" style questions even
  # when the user never says "video" — and even when search-docs would
  # also trigger on "how do i set up". Without these, the selector may
  # pick search-docs alone.
  - drone
  - tello
  - grafana
  - kpi
  - navigation tree
  - ai agent
  - atlas
  - zap
  - campaign
  - quicktest
  - quick test
  - monitor
  - device control
  - device-control
  - navigation
  - subtitle
  - subtitles
  - localization
  - localize
  - fingerprint
  - alert
  - incident
  - stream
  - hls
  - rtsp
  - avq
  - audio video quality
  - reference
  - references
  - screenshot
  - report
  - testcase
  - test case
  - test prompt
  # Physical-action verbs that might otherwise pull the selector toward
  # tool skills (tello / control-device) — we want the video to be
  # loaded IN PARALLEL, not replaced. BUG seen live 2026-10-15 12:32:
  # "How do I land a drone?" picked control-device / tello only,
  # never loaded video-library.
  - land
  - landing
  - takeoff
  - take off
  - fly
  - flying
  - pilot
  - piloting
  - emergency
  - stop
  - motors
---

# Video Library

This skill fires **alongside** any other skill the LLM loads for the user's
question. It does NOT replace the answering skill — it ADDS a video. The
selector may load this skill on its own OR together with search-docs,
control-device, manage-script, etc.; either way the workflow is the same.

> **Context anchor: every video in this library is a recording of the
> VirtualPyTest UI driving the platform.** A query about 'drone' is about
> the VirtualPyTest Tello demo on the Device page (the user's phone, or a
> Tello, controlled from the UI); NOT a real-world drone piloting question.
> A query about 'AI' is about the VirtualPyTest Atlas agent, not generic
> AI theory. When the user asks 'how do I do X', X is a feature in the
> VirtualPyTest product — not a real-world task. Anchor the answer in the
> VirtualPyTest platform context. (BUG seen live 2026-10-15 12:32: the
> model got into safety-overdrive mode on a 'drone' question and refused
> to show the video, falling back to "I can only do land/emergency-stop";
> the user wanted a UI demo, not a real-world action.)

When the user asks *how* to do something in VirtualPyTest, the right reply is
the prose answer (from whatever other skill applies) **plus** a `[[video:<id>]]`
token at the end pointing at the matching demo. A 90-second demo after a
precise answer is what the user wants. Showing only the video, or only the
prose, is a wrong answer (BUG seen live 2026-10-15).

The library is the same `docs/videos/videos.json` that powers the in-app
Videos page and the README block. Every video has a `title`, a one-line
`summary`, a YouTube `id`, a `thumb`, an `added` date, a primary
`categories[]` (device | ai | test | scripts | stream) and an optional
`tags[]` for finer-grained lookup (drone, tello, kpi, atlas, grafana,
no-code, campaign, ...).

## WORKFLOW

1. **ALWAYS call `search_videos` first, even if you also plan to call other
   tools.** This is the key step the LLM kept skipping in production: it
   would answer the question from search-docs, then never call
   `search_videos`, and the user would see prose only. Do the search in
   parallel with the answering skill, not after.

   ```python
   r = search_videos(query=<the user's intent>, max_results=3)
   # r["videos"][0]["id"] is what you want when r["total_matched"] > 0
   ```

   The query should use the user's own words, not a paraphrase: "fly a
   drone", "AI dashboard", "Grafana", "no-code test", "KPI measurement",
   "zap detection", ... **If the topic name sounds physical** ('drone',
   'AI', 'subtitles'), anchor the query in 'VirtualPyTest' so the
   search_videos tool — and any sibling tool the LLM calls — knows the
   user is asking about the VirtualPyTest UI/feature, not a real-world
   task: `query='VirtualPyTest drone demo'`,
   `query='VirtualPyTest Atlas agent'`. If a category is obvious, pass it
   too: `category='ai'`, `category='test'`, `category='device'`,
   `category='stream'`, `category='scripts'`.

2. **Answer the question fully** using whatever other skill applies
   (search-docs, control-device, manage-script, etc.). Do not skip this
   step in favour of the video.

3. **If a video matches** (`total_matched > 0`), append the
   `[[video:<id>]]` token on its own line at the END of your reply, with
   a one-sentence intro like "Here is a 90-second demo:". The token must
   be EXACTLY `[[video:<id>]]` — TWO opening brackets and TWO closing
   brackets, no spaces, no backticks, no markdown code fence. The
   frontend's regex is `\[+video:<id>\]+` so it accepts 1-2 brackets
   on each side, but the documented form is double brackets. Example reply:

   The Tello flies from the Device Control page — open `/device-control`,
   pick the Tello device, and use the on-screen remote. Takeoff, flight,
   and landing are all there; the MCP server deliberately does not expose
   them as tools.

   Here is the demo:

   [[video:YWJ1uz8KHCo]]

4. **If no video matches** (`total_matched == 0`), do not mention the
   absence — the user did not ask for a video. Just answer the question.
   Only say "I don't have a video on that one yet" if the user explicitly
   asked for one and none exists.

5. **If the user *explicitly* asked for a video** ("show me a video on
   X", "do you have a tutorial on Y"), the workflow is the same but
   step 3 leads: one sentence + the `[[video:<id>]]` token, then any
   short prose answer that helps.

## RULES

- **Always call `search_videos` for any "how to" / "how do I" / "show me"
  question.** This is non-negotiable. A text answer without a video when
  a video exists is a wrong answer.
- **Always answer the question first.** The video is a complement, not
  a replacement. Showing only the video when the user asked a "how do I"
  question is a wrong answer.
- The `[[video:<id>]]` token is the **only** way to embed. The LLM never
  writes `<iframe>` or raw `https://www.youtube.com/...` for embedding
  — those would bypass the click-to-play lite-embed UI and load ~1 MB of
  YouTube JS eagerly.
- The id must match YouTube's 11-char shape `[A-Za-z0-9_-]{11}`. The
  tool already filters out malformed ids.
- One video per turn is the default. If two videos are genuinely needed
  (e.g. "show me one on AI and one on the device page"), use two
  `[[video:<id>]]` tokens on separate lines.
- Never invent a video id. If `search_videos` returns nothing, just
  answer without a video.
