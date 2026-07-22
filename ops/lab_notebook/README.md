# Nyctimene Lab Notebook

The permanent scientific record of the project: what was tried, what was observed, and what
it meant. One entry per file, named `LN-00N_slug.md`, numbered in the order entries are opened.

## Convention (non-negotiable)

- **Append-only.** Entries are NEVER edited after the fact. Once an entry records what was
  tried, observed, and concluded, it stands as written.
- **Corrections go in a NEW entry.** If a later entry proves an earlier one wrong, the
  correction is recorded in the new entry and the old entry stands unchanged. The trail of
  what we believed, and when, is itself part of the record.
- **Git history is the immutability guarantee.** Every entry is versioned; nothing is
  silently rewritten. A diff to a past entry should never happen; a new entry should.
- **The notebook is the RECORD; the master context is a SNAPSHOT.** The master context holds
  current state and is overwritten as state changes. The lab notebook holds the permanent,
  append-only history of what happened and why. Do not confuse them: put current state in the
  master context, put the record in the notebook.

## Entries

- `LN-001_arrival_perception_arc.md`
- `LN-002_gen1_space_v2.md`
- `LN-003_line2_substrate.md`

## Related operational references (NOT part of the scientific record)

Operational/environment gotchas do not belong in the append-only LN series (they are not experiments).
They live under `C:\nyctimene\ops\`:
- `nyctimene_workstation_reference.md` — Windows workstation environment (e.g. the AVG TLS-interception
  fix: Python HTTPS is globally fixed via a truststore `.pth`, installed 2026-07-20).
- `nyctimene_box_access_reference.md` — SSH from workstation to the operator box.
- `nyctimene_operator_email_reference.md` — the email command channel.
