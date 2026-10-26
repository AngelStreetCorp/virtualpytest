# BUG-0865 — The screen-label worker named nothing: the model had no room to answer, and the screen/photo question asked about the wrong thing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0865                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | High                                                             |
| Area      | backend_server (screen label worker) / ai                         |
| Fixed in  | build 90145 |
| Commit    | 271756a74                                                        |

---

## Symptom

The TASK-162 daily worker was installed on codebox and fired once. It named **nothing** — and nothing looked
broken. Every row came back "left alone", the run finished `Result=success`, and the journal read like a
healthy job on a quiet night. It was neither: the worker was asking the model a question the model could not
answer, and then asking a second question whose wording was wrong.

Two independent faults, in the same worker, with the same effect.

**1. Every AI call came back empty.** The call log is unambiguous:

```
usage=eval:vision.screen_label profile=minimax-m3-1-flash model=MiniMax-M3.1-Flash-Preview
ok=False error=empty_answer stop_reason=max_tokens tokens_in=352 tokens_out=24
```

`tokens_out=24 of 24` with `stop_reason=max_tokens`: the model used the whole output budget and produced no
text. The **same profile** serving `vision.game_coc_flash` at the same moment finished normally on 62-162
output tokens with `stop_reason=end_turn`.

**2. The screen/photo gate answered "photo" to everything.** With the token budget fixed, the "is this a
picture of a screen?" question was measured against three stored frames, 3 votes each:

| frame | must be | old wording | new wording |
|---|---|---|---|
| blurry photo of a wall (`vpt-pi4/device1`) | PHOTO | PHOTO 3/3 | PHOTO 3/3 |
| Minecraft movie poster (`vpt-pi1/device3`) | SCREEN | **PHOTO 3/3** | SCREEN 3/3 |
| TV broadcast (`vpt-mf1/device3`) | SCREEN | **PHOTO 3/3** | SCREEN 3/3 |

The old wording would have refused **every real screen**. The gate built to stop a photo of a wall from being
named a poster (BUG-0849) was, by itself, stopping everything — including the poster it was built to protect.

## Root cause

**1. The token floor was too small for a thinking model.** The worker asked for `max_tokens=24` per call — a
floor it had raised from 8 earlier, after a different model cut its answer off mid-word. MiniMax M3.1-Flash is a
**thinking** model: the reasoning comes out of the *same* `max_tokens` budget as the answer. At 24 tokens the
model spends the budget thinking and returns no text at all.

Measured on one stored frame, one prompt, 5 calls each:

| `max_tokens` | answer |
|---|---|
| 24 | **empty** every time (`stop_reason=max_tokens`) |
| 64 | `PHOTO` on 4 of 5, and `PH` on the 5th — cut off mid-word |
| 128 | `PHOTO` on 5 of 5 |
| 256 | `PHOTO` on 5 of 5 |

64 truncates; 128 is both complete and stable. The floor was a safety net that had become a wall — and because
an empty answer reads as "this frame is unreadable", the failure was indistinguishable from a quiet night.

**2. The question asked about the CONTENT instead of the MEDIUM.** The wording was:

> *Is this a picture OF a device screen (a TV, monitor, phone or tablet display showing an interface, a menu,
> a video or an image), or a photo of the real world (a room, a wall, **a person, an object**, or a blurry
> close-up)?*

That asks what the picture **depicts**. A full-screen poster of a film depicts a man in a forest, so "a photo
of the real world (a person, an object)" was the better answer, and the model answered PHOTO. A TV broadcast
depicts a room and a person, so it got PHOTO too. The question was about the subject; what the gate needs to
know is whether the **pixels came from a display** or from a camera pointed at the room.

## Fix

`backend_server/scripts/screen_label_worker.py`:

- `MIN_ANSWER_TOKENS = 128` is now the floor for every call (the open-set naming gets
  `OPEN_ANSWER_TOKENS = 256`, because it writes a slug AND a confidence word). The floor is in one place, and
  no caller can ask for less.
- `UI_QUESTION` now asks where the pixels come from, and says explicitly that a picture showing a person or a
  landscape is still SCREEN when the pixels come from a display. The reasoning is in the comment next to the
  question, with the measurement that produced it.

## Verification

The full gate chain, on the three stored frames, after the fix:

```
wall photo        ask_ui -> photo   3/3                        refused, never named
TV broadcast      ask_ui -> screen  3/3 ; ask_live -> live 3/3  live, never named
Minecraft poster  ask_ui -> screen  3/3 ; ask_states -> 'Full-screen poster'
```

`tests/scripts/test_screen_label_worker.py` 37 pass, including two new ones: the floor is 128 and the open-set
budget is not smaller, and no call can go below the floor whatever a caller asks for.

Deployed and re-run from the server that owns the hosts (deploy `46a7c86a`): the worker runs, picks the rows
the metric counts, and leaves every one of them alone — because each one's sample image is unreadable
(the host is not registered with any server, or the host API is down, or the capture file has rotated away).
An unreadable frame is never named, which is the safe direction.

## Prevention

- A token budget for a **thinking** model is not a cap on the answer; it is the room the answer needs. The
  floor is a named constant with the measurement that set it, and a test pins it.
- A question that decides "screen or photograph of the room" must be about the **medium**. A question about
  what the picture shows will be answered about what the picture shows.
- An empty answer is not proof of an unreadable frame. The call log distinguishes them
  (`stop_reason=max_tokens` vs `empty_answer` on a normal end turn), and the worker's own symptom — "named
  nothing, and everything looked fine" — is the kind of failure that hides. A daily job that names nothing
  should say so louder than a job that names nothing because there was nothing to name.
