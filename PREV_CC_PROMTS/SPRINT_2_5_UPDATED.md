# SPRINT_2.5 — API Integration Testing & Manual Sync (updated proposal)

## Original acceptance
- `/sync_sport <sport_type>` admin command returns top-3 актуальных матчей, сохраняет raw_json, source, source_id, валидирует поля, не создаёт дублей, есть интеграционные тесты.

## Observed (current)
- Импорт всех матчей из топ-5 лиг + популярных кубков на неделю вперёд.
- Dedup по api_event_id.
- Dry-run и rate-limit handling.
- Отсутствуют raw_json, source в БД.
- Нет CLI параметров limit/mode.
- Нет интеграционных тестов.

## Recommendation (adopted)
**Keep the extra coverage, but make default behaviour match Roadmap.**  
- Default: `/sync_sport <sport_type>` imports top-3 matches (configurable via flags).  
- Bulk import of all matches remains available via `--mode all` but executes with rate-limit + batching + background worker.

## Acceptance criteria (updated)
1. Default behavior = top-3 (unless explicit flags).  
2. For each DB match record: `api_event_id`, `raw_json`, `source`, `home_team_id`, `away_team_id`, `match_datetime`(UTC) must be present.  
3. No duplicates on repeated runs (atomic upsert).  
4. Integration tests exist for happy path and idempotence.  
5. Documentation updated (CLAUDE.md, README).  

## Tasks
- Add CLI flags `--mode`, `--limit`, `--batch-size`.  
- DB migration: add `raw_json`, `source`, team ids, scores, `match_datetime`.  
- Implement token-bucket limiter and batch processing.  
- Add teams table and cache lookupteam results.  
- Write integration tests (pytest + responses).  
- Update docs.

