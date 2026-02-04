import logging
import os
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = (
    "Ты профессиональный спортивный аналитик. "
    "Пиши краткий, структурированный анализ предстоящего матча на русском. "
    "Без ставок и гарантий, без токсичности. "
    "Используй нейтральный тон и избегай выдуманных фактов, если данных нет."
)


async def generate_match_analysis(match):
    """Сгенерировать анализ матча через GPT."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY не задан, анализ не будет сгенерирован.")
        return None
    client = AsyncOpenAI(api_key=api_key)
    prompt = (
        "Сгенерируй анализ предстоящего матча.\n"
        f"Вид спорта: {match['sport']}\n"
        f"Матч: {match['team1']} vs {match['team2']}\n"
        f"Дата и время: {match['match_date']} {match['match_time']}\n\n"
        "Нужен компактный аналитический обзор (6-10 пунктов), включая:\n"
        "- форма команд и мотивация (без выдуманных конкретных фактов)\n"
        "- стилистика игры и тактические особенности\n"
        "- возможные ключевые факторы матча\n"
        "- аккуратный прогноз динамики игры (без точного счета)\n"
        "Заверши коротким выводом в 1-2 предложениях."
    )
    try:
        response = await client.responses.create(
            model=DEFAULT_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        logger.error("Не удалось получить анализ от GPT: %s", exc)
        return None
    analysis_text = response.output_text
    if not analysis_text:
        return None
    return analysis_text.strip()
