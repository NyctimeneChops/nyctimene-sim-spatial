"""
Tension system (Run 3). The single home of all tension math.

Tension is one scalar (0-100) per agent, tracked internally as per-source
buckets (a JSON column on the models row) and summed for the total:

  PHYSIOLOGICAL = {hunger, thirst}   — accrue per action, escalate once the
      matching days_without_* counter reaches 1, accrue at HALF rate during
      sleep, and resolve ONLY through their real remedy (eat / drink).
  PSYCHOLOGICAL = {failures, shelter, messages} — event/chronic tension.
      Sleep relief (-25) and per-success passive decay (-2) touch these
      buckets ONLY: you cannot sleep away hunger.

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
    TENSION_SLEEP_RATE_MULTIPLIER,
    TENSION_SLEEP_RELIEF,
    TENSION_SUCCESS_DECAY,
    TENSION_THIRST_PER_ACTION,
    TENSION_THIRST_PER_ACTION_ESCALATED,
)

BASE_URL = "http://127.0.0.1:5000"

PHYSIOLOGICAL_SOURCES = ("hunger", "thirst")
PSYCHOLOGICAL_SOURCES = ("failures", "shelter", "messages")
ALL_SOURCES = PHYSIOLOGICAL_SOURCES + PSYCHOLOGICAL_SOURCES

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

def accrue_action_tick(model_id, action_type, is_sleeping=False):
    """
    The per-action state accrual (spec section 2), applied once per action
    cycle before the action executes:

      hunger  +1.5/action (+2.5 once days_without_food >= 1), half during sleep
      thirst  +2.0/action (+3.5 once days_without_water >= 1), half during sleep
      shelter +0.3/action while shelterless, capped at 15, paused during sleep
      messages +0.5/action per pending unanswered message, capped at 15,
               paused during sleep

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
    if is_sleeping:
        hunger_rate *= TENSION_SLEEP_RATE_MULTIPLIER
        thirst_rate *= TENSION_SLEEP_RATE_MULTIPLIER

    sources["hunger"] += hunger_rate
    sources["thirst"] += thirst_rate

    if not is_sleeping:
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


def _relieve_psychological(model_id, amount):
    """
    Remove `amount` of tension across the PSYCHOLOGICAL buckets,
    proportionally to their current values. Physiological buckets are
    untouched — you cannot sleep away hunger.
    """
    sources = parse_sources(_get_model(model_id).get("tension_sources"))
    psych_total = sum(sources[s] for s in PSYCHOLOGICAL_SOURCES)
    if psych_total <= 0:
        return _save(model_id, sources)

    factor = max(0.0, (psych_total - amount) / psych_total)
    for s in PSYCHOLOGICAL_SOURCES:
        sources[s] *= factor
    return _save(model_id, sources)


def apply_sleep_relief(model_id):
    """Successful sleep: -25 across psychological buckets only."""
    return _relieve_psychological(model_id, TENSION_SLEEP_RELIEF)


def apply_success_decay(model_id):
    """Passive decay: -2 across psychological buckets per successful action."""
    return _relieve_psychological(model_id, TENSION_SUCCESS_DECAY)


def day_boundary(model_id):
    """
    Overnight failure fade (spec section 2): at each day boundary the
    failures bucket is halved. Applied after the survival check has recorded
    tension_end_of_day.
    """
    sources = parse_sources(_get_model(model_id).get("tension_sources"))
    sources["failures"] *= TENSION_OVERNIGHT_FAILURE_FADE
    return _save(model_id, sources)
