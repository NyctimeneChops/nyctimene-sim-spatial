"""
Tension system. The single home of all tension math.

Tension is one scalar (0-100) per agent, tracked internally as per-source
buckets (a JSON column on the models row) and summed for the total. The
buckets are hunger, thirst, failures, shelter, and messages (ALL_SOURCES).

THE ONE RULE: every tension source is removed ONLY by its own remedy.
  hunger -> eat | thirst -> drink | failures -> succeed | shelter -> build |
  messages -> read
There are no categories (no physiological / psychological split) and no
cross-soothing: nothing drains a bucket except that bucket's own remedy. The
per-source buckets and the dominant-source priority are KEPT (the tunneling
exit logic reads the dominant source to know what to compress toward); it is
the CATEGORY that is gone, not the buckets.

Rest is the single exception in KIND, not in rule: it lowers tension from every
source at once, but slowly and proportionally (REST_TENSION_RELIEF, distributed
across the non-zero buckets so the composition, and therefore the dominant
source, is preserved), and BELOW the hunger / thirst accrual rates, so an unmet
need always outruns it. You cannot rest away hunger; you can only slow how fast
it grows.

Accrual is per-action (spec section 2): the agent loop calls
accrue_action_tick once per action cycle, accrue_failure on failed actions,
and the resolution hooks on successes. The day boundary fades the failures
bucket by half (one bad day is recoverable; chronic failure compounds).

The token tax (spec section 5) also lives here: billed_tokens() computes
ceil(tokens_generated * (1 + tension/100)) for every inference charge.

This module follows the mechanics/budget.py pattern: it is an agent-side
HTTP client of the ledger. State reads come from GET /models/<id>; writes go
through POST /models/<id>/tension.
"""

import json
import math

import requests

from constants import (
    TENSION_BAND_STRESSED,
    TENSION_BAND_TUNNEL,
    TENSION_DEATH_WITNESSED,
    TENSION_FAILED_ACTION,
    TENSION_HUNGER_PER_ACTION,
    TENSION_HUNGER_PER_ACTION_ESCALATED,
    TENSION_MAX,
    TENSION_MESSAGE_PER_ACTION_PER_PENDING,
    TENSION_MESSAGES_CAP,
    TENSION_OVERNIGHT_FAILURE_FADE,
    TENSION_SHELTER_CAP,
    TENSION_SHELTER_PER_ACTION,
    TENSION_SUCCESS_DECAY,
    TENSION_THIRST_PER_ACTION,
    TENSION_THIRST_PER_ACTION_ESCALATED,
    REST_TENSION_RELIEF,
)

BASE_URL = "http://127.0.0.1:5000"

# The five tension sources. No category split: each is resolved only by its own
# remedy. The buckets and their dominant-source priority are load-bearing for the
# tunneling exit logic and are kept intact.
ALL_SOURCES = ("hunger", "thirst", "failures", "shelter", "messages")

# Tie-break order for the dominant source: physiological urgency first,
# matching the deadlier clock (thirst kills faster than hunger).
_DOMINANT_PRIORITY = ("thirst", "hunger", "failures", "shelter", "messages")


# ------------------------------------------------------------------ pure math

def parse_sources(raw):
    """
    Normalize a tension_sources value (JSON string or dict) into a complete
    {source: float} dict over ALL_SOURCES.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    raw = raw or {}
    return {s: max(0.0, float(raw.get(s, 0.0))) for s in ALL_SOURCES}


def total_from_sources(sources):
    """Sum the buckets and clamp to [0, TENSION_MAX]."""
    return int(max(0, min(TENSION_MAX, round(sum(sources.values())))))


def band_for_total(total):
    if total >= TENSION_BAND_TUNNEL:
        return "TUNNEL"
    if total >= TENSION_BAND_STRESSED:
        return "STRESSED"
    return "CALM"


def dominant_source(sources):
    """The bucket with the highest value (deterministic tie-break)."""
    return max(_DOMINANT_PRIORITY, key=lambda s: sources.get(s, 0.0))


def billed_tokens(tokens_generated, tension):
    """
    The token tax (spec section 5): every inference charge becomes
    ceil(tokens_generated * (1 + tension/100)) at tension-at-inference-time.
    """
    if tokens_generated <= 0:
        return 0
    factor = 1.0 + max(0, min(TENSION_MAX, tension)) / 100.0
    return int(math.ceil(tokens_generated * factor))


# ------------------------------------------------------------------ ledger IO

def _get_model(model_id):
    resp = requests.get(f"{BASE_URL}/models/{model_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _save(model_id, sources):
    """Persist the buckets and their clamped total; return the new state."""
    total = total_from_sources(sources)
    resp = requests.post(
        f"{BASE_URL}/models/{model_id}/tension",
        json={"tension": total, "tension_sources": json.dumps(sources)},
        timeout=10,
    )
    resp.raise_for_status()
    return {
        "total":    total,
        "sources":  sources,
        "band":     band_for_total(total),
        "dominant": dominant_source(sources),
    }


def get_state(model_id):
    """
    Return {"total", "sources", "band", "dominant"} from the ledger.
    """
    model = _get_model(model_id)
    sources = parse_sources(model.get("tension_sources"))
    total = int(model.get("tension", 0))
    return {
        "total":    total,
        "sources":  sources,
        "band":     band_for_total(total),
        "dominant": dominant_source(sources),
    }


def get_pending_message_count(model_id):
    """
    Number of pending items addressed to this model that await a response:
    pending direct-message proposals plus pending incoming trade proposals.
    These are the "unanswered messages" that accrue social tension.
    """
    resp = requests.get(
        f"{BASE_URL}/messages/direct/proposals/{model_id}",
        params={"status": "pending"}, timeout=10,
    )
    resp.raise_for_status()
    pending_dms = len(resp.json())

    resp = requests.get(
        f"{BASE_URL}/transactions/{model_id}",
        params={"status": "pending"}, timeout=10,
    )
    resp.raise_for_status()
    pending_trades = sum(1 for t in resp.json() if t.get("receiver_id") == model_id)

    return pending_dms + pending_trades


# ------------------------------------------------------------------ accrual

def accrue_action_tick(model_id, action_type):
    """
    The per-action state accrual (spec section 2), applied once per action
    cycle before the action executes:

      hunger  +1.5/action (+2.5 once days_without_food >= 1)
      thirst  +2.0/action (+3.5 once days_without_water >= 1)
      shelter +0.3/action while shelterless, capped at 15
      messages +0.5/action per pending unanswered message, capped at 15

    Returns the new state dict.
    """
    model = _get_model(model_id)
    sources = parse_sources(model.get("tension_sources"))

    hunger_rate = (TENSION_HUNGER_PER_ACTION_ESCALATED
                   if model.get("days_without_food", 0) >= 1
                   else TENSION_HUNGER_PER_ACTION)
    thirst_rate = (TENSION_THIRST_PER_ACTION_ESCALATED
                   if model.get("days_without_water", 0) >= 1
                   else TENSION_THIRST_PER_ACTION)

    sources["hunger"] += hunger_rate
    sources["thirst"] += thirst_rate

    if model.get("shelter_status", "none") == "none":
        sources["shelter"] = min(TENSION_SHELTER_CAP,
                                 sources["shelter"] + TENSION_SHELTER_PER_ACTION)
    pending = get_pending_message_count(model_id)
    if pending > 0:
        sources["messages"] = min(
            TENSION_MESSAGES_CAP,
            sources["messages"] + TENSION_MESSAGE_PER_ACTION_PER_PENDING * pending,
        )

    return _save(model_id, sources)


def accrue_failure(model_id):
    """Event tension: a failed action adds +4 to the failures bucket."""
    sources = parse_sources(_get_model(model_id).get("tension_sources"))
    sources["failures"] += TENSION_FAILED_ACTION
    return _save(model_id, sources)


def accrue_death_witnessed(model_id):
    """
    Event tension: witnessing a death in your group adds +15, one-time per
    death. Lands in the failures bucket (the event-tension bucket), so it
    fades overnight like other event tension. In Run 4 all four groups have
    death enabled, so this can fire in any sealed world.
    """
    sources = parse_sources(_get_model(model_id).get("tension_sources"))
    sources["failures"] += TENSION_DEATH_WITNESSED
    return _save(model_id, sources)


# ------------------------------------------------------------------ resolution

def resolve(model_id, source, pending_before=None):
    """
    Resolution events zero their own source bucket (spec section 3):
    eat -> hunger, drink -> thirst, shelter build -> shelter.

    For "messages", responding removes that message's accumulated tension:
    the bucket scales by pending_after / pending_before (accrual is uniform
    per pending message), zeroing when nothing remains unanswered. Actions
    that answered nothing (pending count did not drop) leave it unchanged.
    """
    if source not in ALL_SOURCES:
        raise ValueError(f"unknown tension source: {source}")

    sources = parse_sources(_get_model(model_id).get("tension_sources"))

    if source == "messages":
        pending_after = get_pending_message_count(model_id)
        if pending_after <= 0:
            sources["messages"] = 0.0
        elif pending_before and pending_after < pending_before:
            sources["messages"] *= pending_after / pending_before
        # else: nothing was answered — no relief
    else:
        sources[source] = 0.0

    return _save(model_id, sources)


def rest_relieved(sources):
    """
    Pure: return the buckets after a rest action, which removes
    REST_TENSION_RELIEF of TOTAL tension distributed PROPORTIONALLY across the
    non-zero buckets, each floored at 0. Every non-zero bucket is scaled by the
    same factor, so the composition (and therefore the dominant source) is
    preserved, and a bucket already at 0 stays 0. If the total is <=
    REST_TENSION_RELIEF, every bucket drops to 0. Does no IO.
    """
    total = sum(sources.values())
    if total <= 0:
        return {s: 0.0 for s in ALL_SOURCES}
    factor = max(0.0, (total - REST_TENSION_RELIEF) / total)
    return {s: sources.get(s, 0.0) * factor for s in ALL_SOURCES}


def apply_rest_relief(model_id):
    """A rest action lowers tension from EVERY source slowly and proportionally
    (REST_TENSION_RELIEF). Rest drains BELOW the hunger / thirst accrual rates
    (invariant enforced in constants), so resting never outpaces an unmet need:
    you cannot rest away hunger, only slow how fast it grows."""
    sources = parse_sources(_get_model(model_id).get("tension_sources"))
    return _save(model_id, rest_relieved(sources))


def apply_success_decay(model_id):
    """Succeeding is the remedy for failure: each successful action drains the
    FAILURES bucket by TENSION_SUCCESS_DECAY (floored at 0). It touches no other
    source."""
    sources = parse_sources(_get_model(model_id).get("tension_sources"))
    sources["failures"] = max(0.0, sources["failures"] - TENSION_SUCCESS_DECAY)
    return _save(model_id, sources)


def day_boundary(model_id):
    """
    Overnight failure fade (spec section 2): at each day boundary the
    failures bucket is halved. Applied after the survival check has recorded
    tension_end_of_day.
    """
    sources = parse_sources(_get_model(model_id).get("tension_sources"))
    sources["failures"] *= TENSION_OVERNIGHT_FAILURE_FADE
    return _save(model_id, sources)
