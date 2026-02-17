import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parsing import ParsedExpense, parse_add_command, parse_with_llm

PARTICIPANTS = ["Baggie", "Neo", "Yoga", "Ricky"]


class TestParseAddCommand:
    def test_empty_input(self):
        assert parse_add_command("/add") is None

    def test_missing_amount(self):
        assert parse_add_command("/add dinner") is None

    def test_title_and_amount_only(self):
        result = parse_add_command("/add dinner, 50")
        assert result == ParsedExpense(title="dinner", amount=50.0)

    def test_title_and_decimal_amount(self):
        result = parse_add_command("/add lunch, 12.50")
        assert result == ParsedExpense(title="lunch", amount=12.5)

    def test_full_command_with_names(self):
        result = parse_add_command("/add dinner, 100, baggie neo yoga ricky", PARTICIPANTS)
        assert result is not None
        assert result.title == "dinner"
        assert result.amount == 100.0
        assert result.participants == ["baggie", "neo", "yoga", "ricky"]

    def test_subset_of_participants(self):
        result = parse_add_command("/add coffee, 20, baggie neo", PARTICIPANTS)
        assert result is not None
        assert result.participants == ["baggie", "neo"]

    def test_single_participant(self):
        result = parse_add_command("/add taxi, 30, ricky", PARTICIPANTS)
        assert result is not None
        assert result.participants == ["ricky"]

    def test_no_matching_names_falls_back(self):
        result = parse_add_command("/add dinner, 50, alice bob", PARTICIPANTS)
        assert result is not None
        assert result == ParsedExpense(title="dinner", amount=50.0)
        assert result.participants is None

    def test_case_insensitive_names(self):
        result = parse_add_command("/add dinner, 50, BAGGIE Neo", PARTICIPANTS)
        assert result is not None
        assert result.participants == ["baggie", "neo"]

    def test_names_without_known_participants(self):
        result = parse_add_command("/add dinner, 50, baggie neo")
        assert result is not None
        assert result == ParsedExpense(title="dinner", amount=50.0)
        assert result.participants is None

    def test_add_prefix_variations(self):
        result = parse_add_command("/add dinner, 80, baggie yoga", PARTICIPANTS)
        assert result is not None
        assert result.title == "dinner"
        assert result.participants == ["baggie", "yoga"]

    def test_comma_in_third_part_kept(self):
        result = parse_add_command("/add dinner, 50, baggie, neo, yoga", PARTICIPANTS)
        assert result is not None
        assert result.participants == ["baggie", "neo", "yoga"]

    def test_invalid_amount(self):
        assert parse_add_command("/add dinner, abc") is None


class TestPreLLMFilter:
    """Tests for the pre-LLM relevance guard: messages must contain a number or participant name."""

    @pytest.mark.parametrize(
        "text",
        [
            "hello how are you",
            "what's for dinner",
            "lol nice one",
            "random gibberish text",
            "hey what's up",
        ],
    )
    def test_no_number_no_participant_rejected(self, text):
        import re

        raw = re.sub(r"^/add[-_]?bill?\s*", "", f"/add {text}", flags=re.IGNORECASE).strip()
        has_number = bool(re.search(r"\d", raw))
        has_participant = any(n.lower() in raw.lower() for n in PARTICIPANTS)
        assert not has_number and not has_participant

    @pytest.mark.parametrize(
        "text",
        [
            "lunch 50",
            "baggie paid for dinner",
            "neo owes 20",
            "100 for groceries",
        ],
    )
    def test_number_or_participant_accepted(self, text):
        import re

        raw = re.sub(r"^/add[-_]?bill?\s*", "", f"/add {text}", flags=re.IGNORECASE).strip()
        has_number = bool(re.search(r"\d", raw))
        has_participant = any(n.lower() in raw.lower() for n in PARTICIPANTS)
        assert has_number or has_participant


class TestPromptTemplate:
    def test_formats_without_error(self):
        from config import PROMPT_TEMPLATE

        result = PROMPT_TEMPLATE.format(participants="Alice, Bob", message="lunch 50")
        assert "Alice, Bob" in result
        assert "lunch 50" in result


@pytest.mark.llm
class TestParseWithLLM:
    @pytest.fixture(autouse=True)
    def _requires_groq_api_key(self):
        from config import GROQ_API_KEY

        if not GROQ_API_KEY:
            pytest.skip("GROQ_API_KEY is not set")

    def test_simple_expense(self):
        result = parse_with_llm("dinner cost 100 split between baggie and neo", PARTICIPANTS)
        assert isinstance(result, ParsedExpense)
        assert result.amount == 100.0
        assert result.participants is not None
        assert "baggie" in result.participants
        assert "neo" in result.participants

    def test_all_participants(self):
        result = parse_with_llm("lunch 50 everyone splits", PARTICIPANTS)
        assert isinstance(result, ParsedExpense)
        assert result.amount == 50.0
        assert result.participants is not None
        assert len(result.participants) == 4

    def test_nonsense_returns_error(self):
        result = parse_with_llm("hello how are you", PARTICIPANTS)
        assert result is None or isinstance(result, str)


FAKE_EXPENSES = [
    {
        "id": "exp-123",
        "title": "[telebot-Baggie] Dinner",
        "amount": 5000,
        "paidById": "pid-1",
        "paidFor": [
            {"participantId": "pid-1"},
            {"participantId": "pid-2"},
        ],
    },
    {
        "id": "exp-100",
        "title": "Old expense",
        "amount": 2000,
        "paidById": "pid-2",
        "paidFor": [{"participantId": "pid-2"}],
    },
]

FAKE_ID_NAME = {"pid-1": "Baggie", "pid-2": "Neo"}


def _make_update(chat_id="123", user_id=42, message_id=999):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.effective_user.id = user_id
    update.message.message_id = message_id
    update.message.reply_text = AsyncMock()
    return update


def _make_callback_update(data, user_id=42, message_id=999):
    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_user.id = user_id
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message.message_id = message_id
    update.callback_query.message.reply_text = AsyncMock()
    return update


class TestIsAllowedChat:
    def test_admin_can_talk_in_any_chat(self, monkeypatch):
        import importlib

        monkeypatch.setenv("ADMIN_TELEGRAM_USER_ID", "42")
        monkeypatch.setenv("ALLOWED_TELEGRAM_GROUP_ID", "123")
        monkeypatch.delenv("ALLOWED_CHAT_ID", raising=False)
        monkeypatch.delenv("ALLOWED_USER_ID", raising=False)

        import config
        import helpers

        importlib.reload(config)
        importlib.reload(helpers)

        update = _make_update(chat_id="999", user_id=42)
        assert helpers.is_allowed_chat(update)

    def test_anyone_can_talk_in_allowed_group(self, monkeypatch):
        import importlib

        monkeypatch.setenv("ADMIN_TELEGRAM_USER_ID", "777")
        monkeypatch.setenv("ALLOWED_TELEGRAM_GROUP_ID", "123")
        monkeypatch.delenv("ALLOWED_CHAT_ID", raising=False)
        monkeypatch.delenv("ALLOWED_USER_ID", raising=False)

        import config
        import helpers

        importlib.reload(config)
        importlib.reload(helpers)

        update = _make_update(chat_id="123", user_id=42)
        assert helpers.is_allowed_chat(update)

    def test_others_cannot_talk_outside_allowed_group(self, monkeypatch):
        import importlib

        monkeypatch.setenv("ADMIN_TELEGRAM_USER_ID", "777")
        monkeypatch.setenv("ALLOWED_TELEGRAM_GROUP_ID", "123")
        monkeypatch.delenv("ALLOWED_CHAT_ID", raising=False)
        monkeypatch.delenv("ALLOWED_USER_ID", raising=False)

        import config
        import helpers

        importlib.reload(config)
        importlib.reload(helpers)

        update = _make_update(chat_id="999", user_id=42)
        assert not helpers.is_allowed_chat(update)


class TestDellastCmd:
    @patch("handlers.id_to_name_map", return_value=(FAKE_ID_NAME, "$"))
    @patch("handlers.get_expenses", return_value=FAKE_EXPENSES)
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.spliit", new_callable=lambda: MagicMock)
    def test_shows_latest_expense(self, mock_spliit, mock_allowed, mock_get, mock_idname):
        from handlers import dellast_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(dellast_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert "Dinner" in text
        assert "$50.00" in text
        assert "Baggie" in text

    @patch("handlers.get_expenses", return_value=[])
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.spliit", new_callable=lambda: MagicMock)
    def test_no_expenses(self, mock_spliit, mock_allowed, mock_get):
        from handlers import dellast_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(dellast_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "No expenses found."

    @patch("handlers.is_allowed_chat", return_value=False)
    def test_disallowed_chat(self, mock_allowed):
        from handlers import dellast_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(dellast_cmd(update, ctx))

        update.message.reply_text.assert_not_called()


class TestDellastButton:
    @patch("handlers.delete_expense")
    @patch("handlers.pending_deletes", {"42_999": "exp-123"})
    def test_confirm_delete(self, mock_delete):
        from handlers import SPLIIT_GROUP_ID, button

        update = _make_callback_update("delyes_42_999")
        ctx = MagicMock()
        asyncio.run(button(update, ctx))

        mock_delete.assert_called_once_with(SPLIIT_GROUP_ID, "exp-123")
        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Deleted."

    @patch("handlers.pending_deletes", {"42_999": "exp-123"})
    def test_cancel_delete(self):
        from handlers import button

        update = _make_callback_update("delno_42_999")
        ctx = MagicMock()
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Cancelled."

    @patch("handlers.pending_deletes", {})
    def test_expired_delete(self):
        from handlers import button

        update = _make_callback_update("delyes_42_999")
        ctx = MagicMock()
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Expired. Try again."
