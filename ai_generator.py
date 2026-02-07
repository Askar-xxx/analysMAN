import logging
import os
from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY
from utils import clean_and_truncate

logger = logging.getLogger(__name__)

# Загрузка промпта из внешнего файла
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ANALYSIS_PROMPT.md")
if not os.path.exists(PROMPT_FILE):
    raise FileNotFoundError(
        f"Файл промпта не найден: {PROMPT_FILE}\n"
        "Создайте файл ANALYSIS_PROMPT.md в корне проекта."
    )

with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    ANALYSIS_PROMPT_TEMPLATE = f.read()

client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

SPORT_NAMES = {
    'football': 'футбол',
    'basketball': 'баскетбол',
    'hockey': 'хоккей'
}


async def generate_match_analysis(team1: str, team2: str, sport: str, date: str) -> str:
    """
    Генерирует анализ матча через DeepSeek API.

    Возвращает текст анализа на русском (1200-1800 символов).
    ГАРАНТИРУЕТ, что анализ не превысит 3800 символов.
    Выбрасывает исключение при ошибке API.
    """
    MAX_ANALYSIS_LENGTH = 3800
    TARGET_LENGTH = "1200-1800"

    sport_name = SPORT_NAMES.get(sport, sport)

    prompt = f"""Напиши компактный аналитический обзор предстоящего матча по {sport_name}:
{team1} vs {team2}, дата: {date}.

{ANALYSIS_PROMPT_TEMPLATE}

Замени "команда A" на {team1}, "команда B" на {team2}."""

    system_message = (
        f"Ты — профессиональный спортивный аналитик. "
        f"Пишешь КОМПАКТНЫЕ объективные обзоры матчей на русском языке "
        f"строго в пределах {TARGET_LENGTH} символов. "
        f"АБСОЛЮТНЫЙ МАКСИМУМ: {MAX_ANALYSIS_LENGTH} символов. "
        f"Никогда не даёшь прогнозы на результат, не упоминаешь букмекерские "
        f"коэффициенты и не советуешь ставки. Используешь максимум 4 эмодзи. "
        f"Если текст превышает 2000 символов — обязательно сокращаешь до целевого диапазона."
    )

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1200,
        temperature=0.7
    )

    analysis_text = response.choices[0].message.content.strip()

    # ПОСТ-ОБРАБОТКА: очистка, фильтрация, сокращение
    analysis_text = clean_and_truncate(analysis_text)

    return analysis_text
