# Parser Cleanup — HR dead params + Sleep readability

> Branch: `dev`
> Status: planned, not started · follows the post-refactor hotfix in `75d20e1`
> Scope: two small behavior-preserving refactors to `collector/protocol/parsers/`
> Tracked in: opencode session todo list (this file is the durable backup)

---

## Why

Two issues spotted during the post-refactor review of `collector/protocol/parsers/`:

1. `fetch_hr_history` has dead `start, end` params never read by the body.
2. `_parse_sleep_data` has clever-but-unreadable iteration idioms and magic numbers.

Neither is a bug — both are maintainability liabilities.

---

## Locked constraints

- **Behavior-preserving.** Same bytes in → same records out. No protocol changes.
- **No test additions this round** (deferred pytest suite is `docs/CLEANUP_PLAN.md` Tier 1).
- **Two commits** so each is independently reviewable/revertable.

---

## Commit 1 — `refactor: drop dead params from fetch_hr_history + remove dead wrapper`

**Files:** `collector/protocol/parsers/hr.py`, `collector/sync_ring.py`

1. `hr.py:22` — change signature
   ```python
   # before
   async def fetch_hr_history(client: _Client, start: datetime, end: datetime) -> list[dict]:
   # after
   async def fetch_hr_history(client: _Client) -> list[dict]:
   ```
2. `hr.py:84-88` — delete `fetch_and_store_hr` entirely (zero callers anywhere; uses
   `asyncio.run` from inside a sync function — broken pattern, leftover from Phase 3 split).
3. `sync_ring.py:101` — update the only real call site
   ```python
   # before
   hr_records = await fetch_hr_history(client, None, None)
   # after
   hr_records = await fetch_hr_history(client)
   ```

**Verify:**
- `python3 -m py_compile collector/protocol/parsers/hr.py collector/sync_ring.py`
- `grep -rn "fetch_hr_history\|fetch_and_store_hr" collector/` — expect exactly one caller,
  signature matches
- `python -m collector.analytics` runs (untouched path, sanity only)

---

## Commit 2 — `refactor: improve _parse_sleep_data readability`

**File:** `collector/protocol/parsers/sleep.py` (only `_parse_sleep_data`)

All changes behavior-preserving:

1. **Module constants** (above the function):
   ```python
   _MINUTES_PER_DAY = 1440
   _DAY_BODY_OFFSET = 4   # sleepStart(2) + sleepEnd(2); stage pairs start after this
   ```
2. **Split the semicolon chain** (current lines 42-45) into 4 separate lines.
3. **Kill the magic range** (current line 56):
   ```python
   # before
   for _j in range(4, day_bytes, 2):
       stage_type = data[idx]
       stage_minutes = data[idx + 1]
       idx += 2
   # after
   num_stages = (day_bytes - _DAY_BODY_OFFSET) // 2
   for _ in range(num_stages):
       stage_type = data[idx]
       stage_minutes = data[idx + 1]
       idx += 2
   ```
4. **Use `_MINUTES_PER_DAY`** instead of literal `1440` (current line 50).
5. **Bounds guard** before per-day header read:
   ```python
   if idx + 6 > len(data):
       log.warning(f"Sleep parse truncated at idx={idx}")
       break
   ```
6. **Local counter** replaces the O(N²) filter-log (current line 73):
   ```python
   day_count = 0
   # ... inside the stage loop, after the `stage_minutes == 0` continue:
   day_count += 1
   # ... after the inner loop:
   log.info(f"  Sleep {target_date}: {day_count} stages")
   ```
7. **Comment** above `stage_ts = session_start` explaining why records use
   `stage_ts.date()` (not `target_date`) for the `day` field — pre-midnight
   sessions correctly attribute early stages to the previous calendar day.

**Verify:**
- `python3 -m py_compile collector/protocol/parsers/sleep.py`
- Read full diff line-by-line, confirm no behavior change
- Full regression coverage deferred to pytest suite (`docs/CLEANUP_PLAN.md` Tier 1)

---

## Out of scope

- Adding `tests/test_parsers_sleep.py` with golden-byte fixture (Tier 1 follow-up)
- Refactoring other parsers in `collector/protocol/parsers/`
- Any change to the actual byte protocol or wire format

---

## Resume protocol (if context reset)

1. Check `git log --oneline -5 dev` — if neither commit message is present, start fresh.
2. Check the opencode session todo list — pending items are unstarted.
3. If Commit 1 is in but Commit 2 isn't, skip ahead to the Commit 2 section.
4. Both commits must pass `python3 -m py_compile` before push.
