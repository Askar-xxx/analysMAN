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


def test_match_detail_keyboard_adds_terms_button_for_payment_paths():
    enough_balance = keyboards.match_detail_keyboard(42, False, user_balance=5, price=1)
    low_balance = keyboards.match_detail_keyboard(42, False, user_balance=0, price=1)

    assert enough_balance.inline_keyboard[1][0].callback_data == "terms_from_match_detail"
    assert low_balance.inline_keyboard[1][0].callback_data == "terms_from_match_detail"
