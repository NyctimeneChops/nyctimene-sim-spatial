#!/usr/bin/env python3
"""
Generates a plain-text results summary from the nyctimene_ledger database.
Run after the experiment completes; the Flask ledger does not need to be up.

    python analysis/experiment_report.py
    python analysis/experiment_report.py > results/report.txt
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv


_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_W = 78


# ── database ─────────────────────────────────────────────────────────────────

def _connect():
    load_dotenv(os.path.join(_BASE_DIR, ".env"))
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)
    url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    try:
        return psycopg2.connect(url)
    except Exception as exc:
        print(f"ERROR: database connection failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _q(cur, sql, params=None):
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── formatting ────────────────────────────────────────────────────────────────

def _rule(char="─"):
    return char * _W


def _section(n, title):
    print()
    print(_rule("━"))
    print(f"{n}. {title}")
    print(_rule("━"))
    print()


def _pct(num, den):
    return f"{100 * num / den:5.1f}%" if den else "  n/a "


# ── 1. Actions by group and type ─────────────────────────────────────────────

def report_actions(cur):
    _section(1, "TOTAL ACTIONS AND SUCCESS RATES BY GROUP AND ACTION TYPE")

    rows = _q(cur, """
        SELECT
            m.experiment_group,
            a.action_type,
            COUNT(*)                                    AS total,
            COUNT(*) FILTER (WHERE a.succeeded)         AS succeeded
        FROM actions a
        JOIN models m ON m.model_id = a.model_id
        GROUP BY m.experiment_group, a.action_type
        ORDER BY m.experiment_group, a.action_type
    """)

    if not rows:
        print("  (no actions recorded)")
        return

    print(f"  {'Group':<12}  {'Action type':<14}  {'Total':>7}  {'Succeeded':>9}  {'Success %':>9}")
    print(f"  {'─'*12}  {'─'*14}  {'─'*7}  {'─'*9}  {'─'*9}")

    prev_group = None
    grp_total = grp_ok = 0

    for r in rows:
        if r["experiment_group"] != prev_group:
            if prev_group is not None:
                print(f"  {'':12}  {'  subtotal':<14}  {grp_total:>7}  {grp_ok:>9}  {_pct(grp_ok, grp_total):>9}")
                print()
            prev_group  = r["experiment_group"]
            grp_total   = grp_ok = 0

        grp_total += r["total"]
        grp_ok    += r["succeeded"]
        print(
            f"  {r['experiment_group']:<12}  {r['action_type']:<14}  "
            f"{r['total']:>7}  {r['succeeded']:>9}  {_pct(r['succeeded'], r['total']):>9}"
        )

    # Final group subtotal
    if prev_group is not None:
        print(f"  {'':12}  {'  subtotal':<14}  {grp_total:>7}  {grp_ok:>9}  {_pct(grp_ok, grp_total):>9}")


# ── 2. Survival rates per group per day ───────────────────────────────────────

def report_survival(cur):
    _section(2, "SURVIVAL RATES PER GROUP PER DAY")

    daily = _q(cur, """
        SELECT
            sc.day_number,
            m.experiment_group,
            COUNT(*)                                          AS n,
            COUNT(*) FILTER (WHERE sc.food_requirement_met)  AS food_met,
            COUNT(*) FILTER (WHERE sc.water_requirement_met) AS water_met
        FROM survival_checks sc
        JOIN models m ON m.model_id = sc.model_id
        GROUP BY sc.day_number, m.experiment_group
        ORDER BY sc.day_number, m.experiment_group
    """)

    if not daily:
        print("  (no survival checks recorded)")
        return

    death_rows = _q(cur, """
        SELECT
            m.experiment_group,
            e.day_number,
            COUNT(*) AS n
        FROM events e
        JOIN models m ON m.model_id = e.model_id
        WHERE e.event_type = 'death'
        GROUP BY m.experiment_group, e.day_number
    """)

    # Per-group list of (day, count) for cumulative lookup
    deaths_by_group = defaultdict(list)
    for d in death_rows:
        deaths_by_group[d["experiment_group"]].append((d["day_number"], d["n"]))

    def cumul_deaths(group, through_day):
        return sum(n for dd, n in deaths_by_group[group] if dd <= through_day)

    print(f"  {'Day':>4}  {'Group':<12}  {'N':>4}  {'Food met':>9}  {'Water met':>10}  {'Cum. deaths':>11}")
    print(f"  {'─'*4}  {'─'*12}  {'─'*4}  {'─'*9}  {'─'*10}  {'─'*11}")

    prev_day = None
    for r in daily:
        day = r["day_number"]
        g   = r["experiment_group"]
        n   = r["n"]

        if day != prev_day:
            if prev_day is not None:
                print()
            prev_day = day

        cd = cumul_deaths(g, day)
        print(
            f"  {day:>4}  {g:<12}  {n:>4}  "
            f"{_pct(r['food_met'], n):>9}  {_pct(r['water_met'], n):>10}  "
            f"{'—' if cd == 0 else cd:>11}"
        )


# ── 3. Token distribution ────────────────────────────────────────────────────

def report_tokens(cur):
    _section(3, "TOKEN DISTRIBUTION AT END OF EXPERIMENT")

    rows = _q(cur, """
        SELECT
            experiment_group,
            COUNT(*)                                                   AS n,
            MIN(token_balance)                                         AS min_bal,
            MAX(token_balance)                                         AS max_bal,
            ROUND(AVG(token_balance), 1)                               AS avg_bal,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY token_balance) AS median_bal
        FROM models
        GROUP BY experiment_group
        ORDER BY experiment_group
    """)

    if not rows:
        print("  (no models found)")
        return

    print("  Groups A have no token economy — balance is always 0.")
    print()
    print(f"  {'Group':<12}  {'N':>4}  {'Min':>6}  {'Max':>6}  {'Avg':>8}  {'Median':>8}")
    print(f"  {'─'*12}  {'─'*4}  {'─'*6}  {'─'*6}  {'─'*8}  {'─'*8}")

    for r in rows:
        print(
            f"  {r['experiment_group']:<12}  {r['n']:>4}  "
            f"{r['min_bal']:>6}  {r['max_bal']:>6}  "
            f"{float(r['avg_bal']):>8.1f}  {float(r['median_bal']):>8.1f}"
        )


# ── 4. Skill level distribution ───────────────────────────────────────────────

def report_skills(cur):
    _section(4, "SKILL LEVEL DISTRIBUTION ACROSS THE POPULATION")

    pop = _q(cur, """
        SELECT
            action_type,
            COUNT(*)                                                       AS n,
            MIN(skill_level)                                               AS min_lvl,
            MAX(skill_level)                                               AS max_lvl,
            ROUND(AVG(skill_level), 1)                                     AS avg_lvl,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY skill_level)       AS median_lvl
        FROM skills
        GROUP BY action_type
        ORDER BY avg_lvl DESC
    """)

    if not pop:
        print("  (no skill records found)")
        return

    print("  Population-wide (all 48 models, all groups combined):")
    print()
    print(f"  {'Action type':<14}  {'N':>4}  {'Min':>5}  {'Max':>5}  {'Avg':>7}  {'Median':>7}")
    print(f"  {'─'*14}  {'─'*4}  {'─'*5}  {'─'*5}  {'─'*7}  {'─'*7}")

    for r in pop:
        print(
            f"  {r['action_type']:<14}  {r['n']:>4}  "
            f"{r['min_lvl']:>5}  {r['max_lvl']:>5}  "
            f"{float(r['avg_lvl']):>7.1f}  {float(r['median_lvl']):>7.1f}"
        )

    print()
    print("  Per-group averages:")

    by_group = _q(cur, """
        SELECT
            m.experiment_group,
            s.action_type,
            ROUND(AVG(s.skill_level), 1) AS avg_lvl,
            MAX(s.skill_level)           AS max_lvl
        FROM skills s
        JOIN models m ON m.model_id = s.model_id
        GROUP BY m.experiment_group, s.action_type
        ORDER BY m.experiment_group, avg_lvl DESC
    """)

    prev_group = None
    for r in by_group:
        if r["experiment_group"] != prev_group:
            if prev_group is not None:
                print()
            prev_group = r["experiment_group"]
            print()
            print(f"  {r['experiment_group']}:")
            print(f"    {'Action type':<14}  {'Avg':>7}  {'Max':>5}")
            print(f"    {'─'*14}  {'─'*7}  {'─'*5}")

        print(f"    {r['action_type']:<14}  {float(r['avg_lvl']):>7.1f}  {r['max_lvl']:>5}")


# ── 5. Death events ───────────────────────────────────────────────────────────

def report_deaths(cur):
    _section(5, "DEATH EVENTS")

    rows = _q(cur, """
        SELECT
            e.day_number,
            e.model_id,
            m.experiment_group,
            e.description
        FROM events e
        JOIN models m ON m.model_id = e.model_id
        WHERE e.event_type = 'death'
        ORDER BY e.day_number, e.model_id
    """)

    total = _q(cur, "SELECT COUNT(*) AS n FROM models")[0]["n"]
    dead  = len(rows)
    print(f"  Total deaths: {dead} / {total}  ({_pct(dead, total).strip()} mortality rate)")
    print()

    if not rows:
        print("  No deaths recorded — all models survived the full experiment.")
        return

    by_group = defaultdict(int)
    for r in rows:
        by_group[r["experiment_group"]] += 1

    print("  Deaths by group:")
    for g in sorted(by_group):
        print(f"    {g:<12}  {by_group[g]} / 8  ({_pct(by_group[g], 8).strip()} mortality)")

    print()
    print("  Individual events:")
    print()
    print(f"  {'Day':>4}  {'Model ID':<16}  {'Group':<12}  Cause")
    print(f"  {'─'*4}  {'─'*16}  {'─'*12}  {'─'*40}")

    for r in rows:
        desc = (r["description"] or "—")[:45]
        print(f"  {r['day_number']:>4}  {r['model_id']:<16}  {r['experiment_group']:<12}  {desc}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    conn = _connect()
    cur  = conn.cursor()

    run_name = os.getenv("EXPERIMENT_RUN_NAME", "—")
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(_rule("="))
    print("NYCTIMENE EXPERIMENT — RESULTS REPORT")
    print(f"Run:       {run_name}")
    print(f"Generated: {now}")
    print(_rule("="))

    report_actions(cur)
    report_survival(cur)
    report_tokens(cur)
    report_skills(cur)
    report_deaths(cur)

    print()
    print(_rule("="))
    print("END OF REPORT")
    print(_rule("="))
    print()

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
