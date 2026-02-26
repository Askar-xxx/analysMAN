"""
Модуль для рендеринга аналитических таблиц в WebP через Pillow.
"""
import logging
import os
import platform
from PIL import Image, ImageDraw, ImageFont
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Цветовая схема (светлая тема как в Telegram)
BG_COLOR = '#f0f0f0'  # Фон основной (светло-серый)
CARD_BG = '#ffffff'  # Фон карточки (белый)
TEXT_COLOR = '#1a1a1a'  # Основной текст (почти чёрный)
HEADER_BG = '#e8f0fe'  # Фон заголовков (светло-голубой)
BORDER_COLOR = '#d0d5dd'  # Границы таблицы (серые)
TITLE_COLOR = '#1a73e8'  # Цвет заголовка (синий)

# Размеры (увеличены x2 для высокого разрешения)
SCALE = 2
CARD_WIDTH = 900 * SCALE  # Ширина карточки
CARD_MARGIN = 10 * SCALE  # Внешний отступ карточки от краёв изображения
CARD_PADDING = 20 * SCALE  # Отступы внутри карточки
CELL_PADDING = 12 * SCALE  # Отступы внутри ячеек
HEADER_HEIGHT = 50 * SCALE  # Высота заголовка таблицы
ROW_MIN_HEIGHT = 45 * SCALE  # Минимальная высота строки
TEXT_LINE_SPACING = 6 * SCALE  # Межстрочный интервал внутри ячейки (заметный)
TEXT_PARAGRAPH_SPACING = 4 * SCALE  # Доп. интервал для пустой строки
HISTORY_CELL_PADDING = 8 * SCALE  # Уменьшенный внутренний отступ для правой ячейки "История встреч"

# Ширина колонок (в процентах от общей ширины таблицы)
COL1_WIDTH_PCT = 0.28  # Аспект анализа
COL2_WIDTH_PCT = 0.36  # Команда 1
COL3_WIDTH_PCT = 0.36  # Команда 2

# Пути к шрифтам (Windows / Linux-Docker)
if platform.system() == 'Windows':
    FONT_PATHS = {
        'regular': 'C:\\Windows\\Fonts\\arial.ttf',
        'bold': 'C:\\Windows\\Fonts\\arialbd.ttf',
        'mono': 'C:\\Windows\\Fonts\\cour.ttf',
    }
else:
    # Linux (Docker): apt-get install -y fonts-liberation
    FONT_PATHS = {
        'regular': '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        'bold': '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        'mono': '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',
    }


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Конвертирует HEX цвет в RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _load_font(font_type: str, size: int) -> ImageFont.FreeTypeFont:
    """
    Загружает шрифт с fallback на default.

    Args:
        font_type: 'regular', 'bold', или 'mono'
        size: Размер шрифта

    Returns:
        ImageFont объект
    """
    try:
        font_path = FONT_PATHS.get(font_type, FONT_PATHS['regular'])
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
    except Exception as e:
        logger.warning(f"Не удалось загрузить шрифт {font_type}: {e}")

    # Fallback на default шрифт
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """
    Переносит текст на несколько строк если он превышает max_width.

    Args:
        text: Исходный текст
        font: Шрифт для измерения ширины
        max_width: Максимальная ширина в пикселях

    Returns:
        Список строк с переносами
    """
    if not text:
        return [""]

    # Разбиваем по \n если есть
    lines = text.split('\n')
    wrapped_lines = []

    for line in lines:
        if not line:
            wrapped_lines.append("")
            continue

        # Проверяем помещается ли строка
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]

        if line_width <= max_width:
            wrapped_lines.append(line)
            continue

        # Нужен перенос - разбиваем по словам
        words = line.split(' ')
        current_line = []
        current_width = 0

        for word in words:
            word_bbox = font.getbbox(word + ' ')
            word_width = word_bbox[2] - word_bbox[0]

            if current_width + word_width <= max_width:
                current_line.append(word)
                current_width += word_width
            else:
                # Сохраняем текущую строку и начинаем новую
                if current_line:
                    wrapped_lines.append(' '.join(current_line))
                current_line = [word]
                current_width = word_width

        # Добавляем остаток
        if current_line:
            wrapped_lines.append(' '.join(current_line))

    return wrapped_lines if wrapped_lines else [""]


def _calculate_row_height(cell_texts: List[str], font: ImageFont.FreeTypeFont,
                          col_widths: List[int]) -> int:
    """
    Вычисляет высоту строки на основе самой высокой ячейки.

    Args:
        cell_texts: Список текстов для каждой колонки
        font: Шрифт для измерения
        col_widths: Ширины колонок в пикселях

    Returns:
        Высота строки в пикселях
    """
    max_cell_height = ROW_MIN_HEIGHT

    for i, text in enumerate(cell_texts):
        if i >= len(col_widths):
            continue

        # Вычисляем доступную ширину для текста (минус padding)
        available_width = col_widths[i] - (CELL_PADDING * 2)
        wrapped = _wrap_text(text, font, available_width)
        line_bbox = font.getbbox("A")
        base_line_height = line_bbox[3] - line_bbox[1]
        line_height = base_line_height + TEXT_LINE_SPACING
        empty_lines = sum(1 for line in wrapped if not line.strip())
        cell_height = (len(wrapped) * line_height) + (empty_lines * TEXT_PARAGRAPH_SPACING) + (CELL_PADDING * 2)
        max_cell_height = max(max_cell_height, cell_height)

    return max_cell_height


def _draw_cell(draw: ImageDraw.Draw, x: int, y: int, width: int, height: int,
               text: str, font: ImageFont.FreeTypeFont, is_header: bool = False,
               valign: str = "top", halign: str = "left", padding: int = CELL_PADDING):
    """
    Рисует одну ячейку таблицы с текстом.

    Args:
        draw: ImageDraw объект
        x, y: Координаты верхнего левого угла ячейки
        width, height: Размеры ячейки
        text: Текст для отрисовки
        font: Шрифт
        is_header: Флаг заголовка (другой цвет фона)
        valign: Вертикальное выравнивание текста: top|middle
        halign: Горизонтальное выравнивание текста: left|center
        padding: Внутренний отступ ячейки
    """
    # Рисуем фон ячейки
    bg_color = _hex_to_rgb(HEADER_BG) if is_header else _hex_to_rgb(CARD_BG)
    draw.rectangle([x, y, x + width, y + height], fill=bg_color)

    # Рисуем границы
    border_color = _hex_to_rgb(BORDER_COLOR)
    draw.rectangle([x, y, x + width, y + height], outline=border_color, width=1)

    # Переносим текст если нужно
    available_width = width - (padding * 2)
    wrapped_lines = _wrap_text(text, font, available_width)

    # Рисуем текст построчно
    line_bbox = font.getbbox("A")
    line_height = (line_bbox[3] - line_bbox[1]) + TEXT_LINE_SPACING

    text_block_height = 0
    for line in wrapped_lines:
        text_block_height += line_height
        if not line.strip():
            text_block_height += TEXT_PARAGRAPH_SPACING

    if valign == "middle":
        text_y = y + max(0, (height - text_block_height) // 2)
    else:
        text_y = y + padding
    text_color = _hex_to_rgb(TEXT_COLOR)

    for line in wrapped_lines:
        text_x = x + padding
        if halign == "center":
            line_bbox = font.getbbox(line or " ")
            line_width = line_bbox[2] - line_bbox[0]
            text_x = x + max(padding, (width - line_width) // 2)
        draw.text((text_x, text_y), line, fill=text_color, font=font)
        if not line.strip():
            text_y += TEXT_PARAGRAPH_SPACING
        text_y += line_height


def _compact_history_text(text: str) -> str:
    """Убирает пустые строки в "История встреч", чтобы не было лишнего зазора."""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines)


def render_analysis_table(match: dict, table_data: dict) -> str:
    """
    Рендерит аналитическую таблицу в WebP файл.

    Args:
        match: dict матча (для генерации имени файла)
        table_data: dict с данными для таблицы (из analysis_formatter.build_table_data)

    Returns:
        Путь к созданному WebP файлу
    """
    try:
        # Загружаем шрифты (размеры масштабированы)
        title_font = _load_font('bold', 16 * SCALE)
        header_font = _load_font('bold', 13 * SCALE)
        cell_font = _load_font('regular', 12 * SCALE)

        card_left = CARD_MARGIN
        card_right = CARD_WIDTH - CARD_MARGIN

        # Вычисляем ширины колонок
        table_width = (card_right - card_left) - (CARD_PADDING * 2)
        col1_width = int(table_width * COL1_WIDTH_PCT)
        col2_width = int(table_width * COL2_WIDTH_PCT)
        col3_width = table_width - col1_width - col2_width  # Остаток
        col_widths = [col1_width, col2_width, col3_width]

        # Подготавливаем строки таблицы.
        # Новый формат: адаптивный список rows, старый формат — fallback.
        rows = table_data.get('rows', [])
        if not rows:
            rows = [
                {
                    'label': "Турнирное положение",
                    'left': table_data['tournament_position']['left'],
                    'right': table_data['tournament_position']['right'],
                    'colspan': False
                },
                {
                    'label': "Текущая форма",
                    'left': table_data['current_form']['left'],
                    'right': table_data['current_form']['right'],
                    'colspan': False
                },
                {
                    'label': "Форма дома/на выезде",
                    'left': table_data['home_away']['left'],
                    'right': table_data['home_away']['right'],
                    'colspan': False
                },
                {
                    'label': "Составы",
                    'left': table_data['lineup_changes']['left'],
                    'right': table_data['lineup_changes']['right'],
                    'colspan': False
                },
                {
                    'label': "История встреч",
                    'left': "\n".join(table_data['history']),
                    'right': "",
                    'colspan': True
                },
                {
                    'label': "Статистические тренды",
                    'left': table_data['stats_trends']['left'],
                    'right': table_data['stats_trends']['right'],
                    'colspan': False
                }
            ]

        normalized_rows = []
        for row in rows:
            new_row = dict(row)
            label = str(new_row.get('label', '')).strip().casefold()
            if new_row.get('colspan') and label.startswith("история встреч"):
                new_row['left'] = _compact_history_text(new_row.get('left', ''))
            normalized_rows.append(new_row)
        rows = normalized_rows

        # Вычисляем высоты строк
        row_heights = []
        for row in rows:
            is_history_row = (
                row.get('colspan') and
                str(row.get('label', '')).strip().casefold().startswith("история встреч")
            )
            if row.get('colspan'):
                row_height = _calculate_row_height(
                    [row.get('label', ''), row.get('left', '')],
                    cell_font,
                    [col1_width, col2_width + col3_width]
                )
                if is_history_row:
                    row_height = max(
                        ROW_MIN_HEIGHT,
                        row_height - ((CELL_PADDING - HISTORY_CELL_PADDING) * 2)
                    )
            else:
                row_height = _calculate_row_height(
                    [row.get('label', ''), row.get('left', ''), row.get('right', '')],
                    cell_font,
                    col_widths
                )
            row_heights.append(row_height)

        # Вычисляем общую высоту изображения
        title_height = 60 * SCALE  # Заголовок + отступ
        total_table_height = HEADER_HEIGHT + sum(row_heights)
        total_height = title_height + total_table_height + (CARD_PADDING * 2) + 20 * SCALE

        # Создаём изображение
        img = Image.new('RGB', (CARD_WIDTH, total_height), _hex_to_rgb(BG_COLOR))
        draw = ImageDraw.Draw(img)

        # Рисуем карточку фон
        card_y = CARD_MARGIN
        draw.rounded_rectangle(
            [card_left, card_y, card_right, total_height - CARD_MARGIN],
            radius=8 * SCALE,
            fill=_hex_to_rgb(CARD_BG)
        )

        # Рисуем заголовок
        title_lines = table_data['title'].split('\n')
        title_y = card_y + CARD_PADDING
        for line in title_lines:
            draw.text((card_left + CARD_PADDING, title_y), line,
                      fill=_hex_to_rgb(TITLE_COLOR), font=title_font)
            title_y += 20 * SCALE

        # Начало таблицы
        table_y = title_y + 10 * SCALE

        # Рисуем заголовок таблицы
        header_x = card_left + CARD_PADDING
        _draw_cell(draw, header_x, table_y, col1_width, HEADER_HEIGHT,
                   "Аспект анализа", header_font, is_header=True)
        _draw_cell(draw, header_x + col1_width, table_y, col2_width,
                   HEADER_HEIGHT, table_data['team_left'], header_font,
                   is_header=True)
        _draw_cell(draw, header_x + col1_width + col2_width, table_y,
                   col3_width, HEADER_HEIGHT, table_data['team_right'],
                   header_font, is_header=True)

        table_y += HEADER_HEIGHT

        # Рисуем строки данных
        for i, row in enumerate(rows):
            row_height = row_heights[i]
            label = row.get('label', '')
            left = row.get('left', '')
            right = row.get('right', '')

            # Строка с объединёнными правыми колонками
            if row.get('colspan'):
                is_history_row = str(label).strip().casefold().startswith("история встреч")
                _draw_cell(draw, header_x, table_y, col1_width, row_height,
                           label, cell_font, valign="top")
                _draw_cell(draw, header_x + col1_width, table_y,
                           col2_width + col3_width, row_height, left,
                           cell_font,
                           valign="middle" if is_history_row else "top",
                           halign="center" if is_history_row else "left",
                           padding=HISTORY_CELL_PADDING if is_history_row else CELL_PADDING)
            else:
                # Обычная строка с 3 колонками
                _draw_cell(draw, header_x, table_y, col1_width, row_height,
                           label, cell_font)
                _draw_cell(draw, header_x + col1_width, table_y, col2_width,
                           row_height, left, cell_font)
                _draw_cell(draw, header_x + col1_width + col2_width, table_y,
                           col3_width, row_height, right, cell_font)

            table_y += row_height

        # Сохраняем изображение
        match_id = match.get('id', 'unknown')
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(output_dir, f'analysis_{match_id}.webp')
        img.save(output_path, 'WEBP', quality=90)

        logger.info(f"WebP таблица сохранена: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Ошибка рендеринга WebP: {e}", exc_info=True)
        raise
