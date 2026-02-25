"""Tests for keyboard callback-data behavior."""
import keyboards


def _callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def test_analysis_view_keyboard_default_callbacks():
    markup = keyboards.analysis_view_keyboard(
        match_id=42,
        back_callback_data="back_custom",
        callback_suffix="purchased",
    )
    callbacks = _callbacks(markup)

    assert callbacks[0] == ["show_table_42_purchased", "show_text_42_purchased"]
    assert callbacks[1] == ["back_custom"]
    assert callbacks[2] == ["back_to_menu"]


def test_analysis_view_keyboard_table_button_noop_when_active():
    markup = keyboards.analysis_view_keyboard(
        match_id=42,
        back_callback_data="back_custom",
        callback_suffix="purchased",
        active_view="table",
    )
    callbacks = _callbacks(markup)

    assert callbacks[0] == ["noop", "show_text_42_purchased"]


def test_analysis_view_keyboard_text_button_noop_when_active():
    markup = keyboards.analysis_view_keyboard(
        match_id=42,
        back_callback_data="back_custom",
        callback_suffix="purchased",
        active_view="text",
    )
    callbacks = _callbacks(markup)

    assert callbacks[0] == ["show_table_42_purchased", "noop"]
