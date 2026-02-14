# Claude Code — Sprint 2.5 Sync Instructions

## Purpose
Bring the current Sprint 2.5 implementation into **ROADMAP.md compliance**  
**without removing** the extended (bulk) functionality already implemented.

> Key principle: **parameterize, do not revert**.

---

## Authoritative Spec
- `ROADMAP.md` is the **single source of truth** for acceptance criteria.
- Current codebase contains **extended functionality** that must be preserved but made optional.

---

## Current State (Observed)
The current implementation already includes:
- Bulk import of matches (top-5 leagues + cups, multiple days).
- Deduplication via `api_event_id`.
- Dry-run support.
- Basic rate-limit handling (sleep-based).

This is considered an **extended implementation**, not a Sprint 2.5 baseline.

---

## Target State (Sprint 2.5 Compliance)

### Default Behavior (MANDATORY)
- Default sync imports **top-3 matches only**.
- No bulk behavior unless explicitly enabled by flags.

### Optional Behavior (ALLOWED)
- Bulk import of all matches must remain available via CLI flags.
- Bulk mode must respect rate limits and batching.

---

## Required Changes (High Priority)

### 1. CLI Parameterization
Add CLI flags to `sync_matches.py`:
- `--mode {top3,all}` (default: `top3`)
- `--limit N` (default: 3 when mode=top3)
- `--batch-size N`
- `--dry-run`

---

### 2. Database Tracing & Schema
Add and persist the following fields:
- `raw_json` (full API response per match)
- `source` (e.g. `"TheSportsDB"`)
- `home_team_id`, `away_team_id`
- `home_score`, `away_score`
- `match_datetime` (UTC, ISO8601)

Requirements:
- `api_event_id` must remain UNIQUE.
- Inserts must be **idempotent** (upsert behavior).

---

### 3. Rate Limiting & Batch Processing
- Implement token-bucket limiter (safe: ~25 req/min).
- Process matches in batches.
- Apply exponential backoff on HTTP 429.

---

### 4. Teams Caching
- Add `teams` table for `lookupteam` results.
- Cache team metadata (TTL ~24h).
- Avoid repeated API calls for the same team.

---

### 5. Integration Tests (MANDATORY)
Add pytest-based integration tests:
- Sync default (`top3`) inserts exactly 3 matches.
- Re-running sync does not create duplicates.
- Each saved match includes `api_event_id`, `raw_json`, `source`.

Mocks:
- TheSportsDB endpoints (`eventsnextleague`, `lookupevent`, `lookupteam`).

---

## Rules for Claude Code (IMPORTANT)

Before writing any code, CC MUST:
1. Read files in order:
   - `ROADMAP.md`
   - `sprint_2_5_реализовано_добавление_матчей_без_подробной_статистики.txt`
   - `sync_matches.py`, `database.py`, `add_test_match.py`
2. Produce:
   - A short summary of **current vs target state**.
   - A table mapping ROADMAP requirements → implemented (Yes/No).
   - A proposed **commit plan** (atomic commits).
3. **Wait for explicit approval** before modifying code.

---

## Development Rules
- Do NOT remove existing bulk functionality.
- Do NOT change defaults unless required by ROADMAP.
- All work must be done in branch: `fix/sync-parametrize-and-trace`.
- Commits must be small and atomic.
- Tests must pass (`pytest tests/`) before PR.

---

## Definition of Done
- Default sync = top-3 matches.
- Bulk sync available via flags.
- Full tracing (`raw_json`, `source`) present.
- Idempotent DB writes.
- Rate limits respected.
- Integration tests green.
- Documentation updated if behavior changed.

