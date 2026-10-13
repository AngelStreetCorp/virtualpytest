"""AI usage keys owned by the companion feature (routed in Settings -> AI like core keys).

Registered by features/companion/backend_server when the server loads the feature, so a
deployment with the feature disabled has none of them in its catalogue.
"""

from shared.src.lib.ai import usages

IDENTIFY = "vision.companion"
LIVE_READ = "vision.companion.roi"
FACTS = "text.web.companion"
DIGEST = "text.companion.digest"
FACTCHECK = "text.web.companion.factcheck"
# Live-TV companion sentence meter (TASK-45): one decision-model call per scored sentence.
# Inherits text.decision, so routes to the Jev profile like other decision calls.
METER = "text.decision.companion"
# Live-TV companion gates (TASK-45 goal 5): one Jev call decides whether to SKIP an LLM / web call.
# Three gates (factcheck / facts / digest) all use this single key; the call site passes the gate
# name in refs. Decision model only (parent text.decision routes to the Jev profile).
GATE = "text.decision.companion.gate"


def register_usages() -> None:
    usages.register(
        usages.feature_usage(IDENTIFY, "Live-TV companion: identify",
                             "What is on screen: screen type, category, programme", "vision",
                             output="json", thinking="off"),
        usages.feature_usage(LIVE_READ, "Live-TV companion: live read",
                             "Read live values from a screen region (scoreboard)", IDENTIFY),
        # Under text.web: answered only with a live web search, never from model memory.
        # Text only (transcript + on-screen text): fine on a small local model.
        usages.feature_usage(DIGEST, "Live-TV companion: digest",
                             "Stories / topics from the last minutes of transcript and on-screen text", "text",
                             output="json", thinking="off"),
        usages.feature_usage(FACTS, "Live-TV companion: facts",
                             "Facts about the identified programme (cast, lineups...)", "text.web",
                             output="json"),
        # Opt-in per device (DEVICE{N}_COMPANION_FACTCHECK), capped per hour; inherits the web need.
        usages.feature_usage(FACTCHECK, "Live-TV companion: fact check",
                             "Checks a factual claim made in a debate against a web search", FACTS,
                             output="json"),
        # Sentence meter (TASK-45): one Jev call per scored sentence, plus the speaker pick.
        # Decision model only (parent text.decision routes to the Jev profile).
        usages.feature_usage(METER, "Live-TV companion: sentence meter",
                             "Scores each subtitled sentence and picks the speaker (decision model)",
                             "text.decision"),
        # Jev gates (TASK-45 goal 5): fail open, skip an LLM / web call when Jev thinks it is not
        # worth it (a vague or repeat claim, a non-programme title, a digest with nothing new).
        usages.feature_usage(GATE, "Live-TV companion: LLM gate",
                             "Decides whether a companion LLM / web call is worth making (decision model)",
                             "text.decision"),
    )
