-- Миграция: добавление полей API-Football в таблицу matches
-- Дата: 2026-02-11
-- Контекст: Этап 2 — сохранение данных API-Football в БД
-- Решения: см. API_FOOTBALL_DECISIONS.md

-- Team statistics (статистика дома/в гостях, форма)
ALTER TABLE matches ADD COLUMN apif_stats_json TEXT;
ALTER TABLE matches ADD COLUMN apif_stats_fetched_at TEXT;

-- Injuries (травмированные игроки обеих команд)
ALTER TABLE matches ADD COLUMN apif_injuries_json TEXT;
ALTER TABLE matches ADD COLUMN apif_injuries_fetched_at TEXT;

-- Full standings (полная таблица лиги, все команды)
ALTER TABLE matches ADD COLUMN apif_full_standings_json TEXT;
ALTER TABLE matches ADD COLUMN apif_standings_fetched_at TEXT;

-- Team ID mapping: колонка в таблице teams
ALTER TABLE teams ADD COLUMN apif_team_id TEXT;
