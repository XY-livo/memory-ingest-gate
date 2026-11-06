# The Ingest Gate

> **A memory library should only store judgements you will need again — never process.**
> The gate's job is to force "things that look like conclusions" into a **testable shape**, then route them by evidence strength.

A write-gate for AI memory stores / knowledge bases. No prompt tricks, no "please remember" — just **validation order**.

```
validate → duplicate → conflict → usefulness → level routing
```

The order *is* the logic: **check duplicates before conflicts, and only then talk about levels.** Reverse it and every duplicate becomes a "conflict" in your review queue.

---

## Why it exists

Four failure modes of AI-written memory:

| Smell | What the gate does |
|---|---|
| One person, three spellings — retrieval misses all | Entities must be registered first; unknown subject is rejected |
| Conclusions can't be traced — hearsay | `source_ref` must resolve to a line/event, or it's rejected |
| Duplicates get mistaken for conflicts | Duplicate check runs first → reject and return the existing id |
| Unverified facts sit next to verified ones | Five evidence levels; V3 only goes to a candidates area; V4 is `refuted` |

---

## Quickstart (60s)

```bash
python3 src/gate.py init --vault vault
python3 src/gate.py entity add E01 "Some Person" --note "external contact"

cat > c.json <<'JSON'
{"layer":"L2","subject":"E01","relation":"believes",
 "object":"Sort by mtime before bulk renaming","dimension":"workflow",
 "valid_from":"2026-11-06","source":"chat","source_ref":"inbox/20261106.md#L12",
 "level":"V1","level_by":"agent","verify":"run the rename once, 3 new names printed",
 "use_when":"bulk-renaming invoices or photos"}
JSON

python3 src/gate.py --vault vault add --json c.json
# {"ok": true, "status": "active", "id": "C-20261106-001", "where": "claims"}
```

Submit the same thing again → `{"ok": false, "status": "duplicate", "existing": "C-20261106-001"}`.
**The gate does not let you write twice; it sends you back to edit the one that exists.**

Self-test (never touches your vault):

```bash
python3 src/gate.py selftest
```

---

## Five evidence levels, four hard rules

| Level | Meaning | Who may set it |
|---|---|---|
| **V0** | Owner's own rule (constitutional) | **Owner only**; agents are rejected |
| **V1** | Verified — reproducible on this machine | Agent allowed, but `verify` must say how |
| **V2** | Corroborated — docs / web / someone's account | Top level an agent may assign |
| **V3** | Unverified | Candidates area only (`N-` prefix) |
| **V4** | Refuted | Status `refuted`, excluded from recall |

1. **V0 is owner-only**
2. **Upgrades are one step at a time** (V3→V2→V1→V0); skipping is rejected, and the message tells you the ceiling
3. **Downgrades are owner-only** — agents can never downgrade; each step appends a line to the entry's `## History`
4. **The closer to fact, the harder**: if it can't be reproduced, it gets downgraded

---

## Conflicts are never silently overwritten

- Same entity + relation + dimension + different value + overlapping interval → goes to `queue/`
- Different `condition` → treated as coexisting (`coexist_with`)
- **But if either side is V0, `condition` is not a reason to coexist — it becomes `needs_review` (human)**
- Resolve with `keep-a` / `keep-b` / `keep-both`; the loser becomes `superseded`, with history

---

## What it deliberately does not do

- No vectors, no RAG, no model calls — it only guards **the door**
- It doesn't judge whether the content is true; it guarantees every entry is **testable, traceable, refutable**
- No framework lock-in: one directory + one dependency-free Python 3 script

---

## Design notes (the interesting part)

`docs/设计取舍.md` (Chinese) explains *why*:

- why duplicate-check must precede conflict-check
- why only a human may downgrade a level
- why "rules" require a `dimension`
- why V3 must live apart from verified facts
- why process logs must never enter the library

---

## License

MIT
