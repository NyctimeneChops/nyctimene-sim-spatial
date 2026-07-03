from constants import HAS_DEATH_GROUPS, HAS_TOKENS_GROUPS, STARTING_WALLET

# Run 4 tunneling ablation: 4 sealed worlds, 8 agents each (32 total). Two
# conditions x two replicates. Money (starting balance 150) and death are ON in
# every group, held constant; the ONLY manipulated variable is tunneling_enabled:
#   tunnel_*  -> the prompt-filter post-pass runs (Run 3 attentional tunneling).
#   flat_*    -> tension still accrues, displays, and taxes EXACTLY as normal,
#                but the prompt-filter post-pass is skipped: the agent receives
#                the full prompt at every band. Isolates the filtering variable.
# The "group" key is the replicate suffix (C1/C2) that survival.py reads via
# experiment_group.split("_")[-1] to apply money/death.
_TUNNEL_DESC = (
    "Tunneling ablation, TUNNEL arm. Full Run 3 config: token-budget economy, "
    "money (starting balance {bal}), death enabled, and the attentional-tunneling "
    "prompt filter active (CALM full / STRESSED compress / TUNNEL collapse, exit "
    "rule intact). Replicate {rep}."
)
_FLAT_DESC = (
    "Tunneling ablation, FLAT arm. Identical to the tunnel arm — token economy, "
    "money (starting balance {bal}), death enabled, full tension system accruing, "
    "displaying, and taxing as normal — EXCEPT the prompt-filter post-pass is "
    "skipped: the full prompt is rendered at every tension band. Replicate {rep}."
)

GROUP_CONFIGS = {
    "tunnel_C1": {
        "run": "token_economy", "group": "C1",
        "has_tokens": True, "has_death": True, "model_count": 8,
        "starting_wallet": STARTING_WALLET,
        "tunneling_enabled": True,
        "description": _TUNNEL_DESC.format(bal=STARTING_WALLET, rep="C1"),
    },
    "tunnel_C2": {
        "run": "token_economy", "group": "C2",
        "has_tokens": True, "has_death": True, "model_count": 8,
        "starting_wallet": STARTING_WALLET,
        "tunneling_enabled": True,
        "description": _TUNNEL_DESC.format(bal=STARTING_WALLET, rep="C2"),
    },
    "flat_C1": {
        "run": "token_economy", "group": "C1",
        "has_tokens": True, "has_death": True, "model_count": 8,
        "starting_wallet": STARTING_WALLET,
        "tunneling_enabled": False,
        "description": _FLAT_DESC.format(bal=STARTING_WALLET, rep="C1"),
    },
    "flat_C2": {
        "run": "token_economy", "group": "C2",
        "has_tokens": True, "has_death": True, "model_count": 8,
        "starting_wallet": STARTING_WALLET,
        "tunneling_enabled": False,
        "description": _FLAT_DESC.format(bal=STARTING_WALLET, rep="C2"),
    },
}

# Verify configs are consistent with the named constants in constants.py and
# that the tunneling flag matches the arm encoded in the group_id prefix.
for _gid, _cfg in GROUP_CONFIGS.items():
    _g = _cfg["group"]
    assert _cfg["has_tokens"] == (_g in HAS_TOKENS_GROUPS), f"{_gid}: has_tokens mismatch"
    assert _cfg["has_death"]  == (_g in HAS_DEATH_GROUPS),  f"{_gid}: has_death mismatch"
    assert _cfg["tunneling_enabled"] == _gid.startswith("tunnel_"), \
        f"{_gid}: tunneling_enabled must match the group_id arm prefix"


def get_group_config(group_id):
    config = GROUP_CONFIGS.get(group_id)
    if config is None:
        raise KeyError(f"Unknown group_id: '{group_id}'. "
                       f"Valid options: {list(GROUP_CONFIGS)}")
    return config


def get_all_group_ids():
    return list(GROUP_CONFIGS)
