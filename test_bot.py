import asyncio
import json
import logging
import urllib.error
import urllib.request
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli import (
    add_cmd as cli_add_cmd,
)
from cli import (
    balance_cmd as cli_balance_cmd,
)
from cli import (
    build_parser,
    list_reimbursements,
    mark_reimbursement_paid,
)
from cli import (
    group_cmd as cli_group_cmd,
)
from cli import (
    latest_cmd as cli_latest_cmd,
)
from cli import (
    undo_cmd as cli_undo_cmd,
)
from domain import Activity, BalanceReport, Group, ParticipantDirectory, Reimbursement
from domain.expense import ExpenseDraft, LLMParsedExpense, ParseFailure
from domain.split import SplitMode, parse_split_values
from llm.parser import parse_add_command, parse_with_llm
from spliit_integration.gateway import NewExpense, Settlement
from telegram_bot.session import PendingDelete, PendingSettlement
from telegram_bot.ui import build_expense_confirmation

PARTICIPANTS = ["Baggie", "Neo", "Yoga", "Ricky"]


class TestParseAddCommand:
    def test_empty_input(self):
        assert parse_add_command("/add") is None

    def test_missing_amount(self):
        assert parse_add_command("/add dinner") is None

    def test_title_and_amount_only(self):
        result = parse_add_command("/add dinner, 50")
        assert result == LLMParsedExpense(title="dinner", amount=50.0)

    def test_title_and_decimal_amount(self):
        result = parse_add_command("/add lunch, 12.50")
        assert result == LLMParsedExpense(title="lunch", amount=12.5)

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
        assert result == LLMParsedExpense(title="dinner", amount=50.0)
        assert result.participants is None

    def test_case_insensitive_names(self):
        result = parse_add_command("/add dinner, 50, BAGGIE Neo", PARTICIPANTS)
        assert result is not None
        assert result.participants == ["baggie", "neo"]

    def test_names_without_known_participants(self):
        result = parse_add_command("/add dinner, 50, baggie neo")
        assert result is not None
        assert result == LLMParsedExpense(title="dinner", amount=50.0)
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
        from llm.parser import prompt_template

        result = prompt_template().format(participants="Alice, Bob", message="lunch 50")
        assert "Alice, Bob" in result
        assert "lunch 50" in result


class _FakeCompletionMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeCompletionChoice:
    def __init__(self, content: str):
        self.message = _FakeCompletionMessage(content)


class _FakeCompletion:
    def __init__(self, content: str):
        self.choices = [_FakeCompletionChoice(content)]


class _FakeInstructorCompletions:
    def __init__(self, responses: list[tuple[object, _FakeCompletion]]):
        self._responses = responses

    async def create_with_completion(self, *args, **kwargs):
        return self._responses.pop(0)


class _FakeInstructorChat:
    def __init__(self, responses: list[tuple[object, _FakeCompletion]]):
        self.completions = _FakeInstructorCompletions(responses)


class _FakeInstructorClient:
    def __init__(self, responses: list[tuple[object, _FakeCompletion]]):
        self.chat = _FakeInstructorChat(responses)


class TestExpenseConfirmation:
    def test_builds_pending_expense_without_storing_it(self):
        from telegram_bot.session import PENDING_ACTIONS_KEY

        draft = ExpenseDraft.with_participants({"Baggie": "pid-1", "Neo": "pid-2", "Yoga": "pid-3"})
        draft.title = "Dinner"
        draft.amount = 42.5
        draft.set_payer_id("pid-1")
        draft.payee_ids = ["pid-1", "pid-2"]

        bot_data: dict = {}
        confirmation = build_expense_confirmation(
            draft,
            key="confirm-key",
            tg_name="Baggie",
            group_id="group-1",
            currency="$",
        )

        assert "Dinner" in confirmation.text
        assert "42.50" in confirmation.text
        assert confirmation.pending_expense.expense.title == "Dinner"
        assert confirmation.pending_expense.expense.amount_cents == 4250
        assert confirmation.pending_expense.expense.paid_for == [("pid-1", 1), ("pid-2", 1)]
        assert PENDING_ACTIONS_KEY not in bot_data


class TestParseWithInstructor:
    def test_parses_structured_response(self):
        import llm.parser as parsing

        raw = '{"title":"Lunch","amount":12.5,"payer":"Baggie","participants":["Baggie","Neo"]}'
        responses = [
            (
                parsing.LLMExpenseResponse(
                    title="Lunch", amount=12.5, payer="Baggie", participants=["Baggie", "Neo"]
                ),
                _FakeCompletion(raw),
            )
        ]

        with (
            patch.object(parsing, "GROQ_API_KEY", "test-key"),
            patch.object(parsing, "from_groq", return_value=_FakeInstructorClient(responses)),
        ):
            result, raw_response = asyncio.run(
                parse_with_llm("baggie paid lunch 12.5 split with neo", PARTICIPANTS)
            )

        assert isinstance(result, LLMParsedExpense)
        assert result.title == "Lunch"
        assert result.amount == 12.5
        assert result.payer == "Baggie"
        assert result.participants == ["baggie", "neo"]
        assert raw_response == raw

    def test_clears_inferred_payer_without_explicit_payer_signal(self):
        import llm.parser as parsing

        responses = [
            (
                parsing.LLMExpenseResponse(
                    title="movie", amount=28, payer="Neo", participants=["Neo", "Yoga"]
                ),
                _FakeCompletion(""),
            )
        ]

        with (
            patch.object(parsing, "GROQ_API_KEY", "test-key"),
            patch.object(parsing, "from_groq", return_value=_FakeInstructorClient(responses)),
        ):
            result, _ = asyncio.run(parse_with_llm("movie 28 shared by neo and yoga", PARTICIPANTS))

        assert isinstance(result, LLMParsedExpense)
        assert result.payer is None
        assert result.participants == ["neo", "yoga"]

    def test_keeps_payer_when_explicit_payer_signal_exists(self):
        import llm.parser as parsing

        responses = [
            (
                parsing.LLMExpenseResponse(
                    title="fries", amount=6.5, payer="Neo", participants=["Neo", "Ricky"]
                ),
                _FakeCompletion(""),
            )
        ]

        with (
            patch.object(parsing, "GROQ_API_KEY", "test-key"),
            patch.object(parsing, "from_groq", return_value=_FakeInstructorClient(responses)),
        ):
            result, _ = asyncio.run(
                parse_with_llm("neo bought fries 6.5 for neo + ricky", PARTICIPANTS)
            )

        assert isinstance(result, LLMParsedExpense)
        assert result.payer == "Neo"
        assert result.participants == ["neo", "ricky"]


@pytest.mark.llm
class TestParseWithLLM:
    @pytest.fixture(autouse=True)
    def _requires_groq_api_key(self):
        from config import GROQ_API_KEY

        if not GROQ_API_KEY:
            pytest.skip("GROQ_API_KEY is not set")

    def test_simple_expense(self):
        result, _ = asyncio.run(
            parse_with_llm("dinner cost 100 split between baggie and neo", PARTICIPANTS)
        )
        assert isinstance(result, LLMParsedExpense)
        assert result.amount == 100.0
        assert result.participants is not None
        assert "baggie" in result.participants
        assert "neo" in result.participants

    def test_all_participants(self):
        result, _ = asyncio.run(parse_with_llm("lunch 50 everyone splits", PARTICIPANTS))
        assert isinstance(result, LLMParsedExpense)
        assert result.amount == 50.0
        assert result.participants is not None
        assert len(result.participants) == 4

    def test_nonsense_returns_error(self):
        result, _ = asyncio.run(parse_with_llm("hello how are you", PARTICIPANTS))
        assert result is None or isinstance(result, ParseFailure)


FAKE_EXPENSES = [
    {
        "id": "exp-123",
        "title": "[telebot-Baggie] Dinner",
        "amount": 5000,
        "paidBy": {"id": "pid-1", "name": "Baggie"},
        "paidFor": [
            {"participant": {"id": "pid-1", "name": "Baggie"}},
            {"participant": {"id": "pid-2", "name": "Neo"}},
        ],
    },
    {
        "id": "exp-100",
        "title": "Old expense",
        "amount": 2000,
        "paidBy": {"id": "pid-2", "name": "Neo"},
        "paidFor": [{"participant": {"id": "pid-2", "name": "Neo"}}],
    },
]

FAKE_ACTIVITIES = [
    Activity(activity_type="CREATE_EXPENSE", subject="Dinner", expense_id="exp-123"),
    Activity(activity_type="UPDATE_GROUP", subject="Untitled"),
    Activity(activity_type="DELETE_EXPENSE", subject="Taxi", expense_id="exp-deleted"),
]

FAKE_BALANCES = BalanceReport(
    balances=[],
    reimbursements=[
        Reimbursement(from_id="pid-1", to_id="pid-2", amount_cents=1250),
        Reimbursement(from_id="pid-3", to_id="pid-2", amount_cents=2500),
    ],
)


def _make_update(chat_id="123", user_id=42, message_id=999, chat_type="group", text="/cmd"):
    update = MagicMock()
    update.effective_chat.id = int(chat_id)
    update.effective_chat.type = chat_type
    update.effective_user.id = user_id
    update.effective_user.first_name = "Baggie"
    update.message.message_id = message_id
    update.message.text = text
    update.message.from_user = update.effective_user
    update.message.reply_text = AsyncMock()
    return update


def _make_callback_update(data, user_id=42, message_id=999, chat_type="group"):
    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_chat.type = chat_type
    update.effective_user.id = user_id
    update.effective_user.first_name = "Baggie"
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message.message_id = message_id
    update.callback_query.message.reply_text = AsyncMock()
    update.callback_query.message.from_user = update.effective_user
    return update


class TestIsAllowedChat:
    def test_admin_can_talk_in_any_chat(self, monkeypatch, tmp_path):
        import importlib

        groups_path = tmp_path / "groups.json"
        groups_path.write_text(json.dumps({"123": "trip-123"}))
        monkeypatch.setenv("ADMIN_TELEGRAM_USER_ID", "42")
        monkeypatch.setenv("GROUPS_JSON_PATH", str(groups_path))
        monkeypatch.delenv("ALLOWED_CHAT_ID", raising=False)
        monkeypatch.delenv("ALLOWED_USER_ID", raising=False)

        import config
        import telegram_bot.access as helpers

        importlib.reload(config)
        importlib.reload(helpers)

        update = _make_update(chat_id="999", user_id=42)
        assert helpers.is_allowed_chat(update)

    def test_anyone_can_talk_in_allowed_group(self, monkeypatch, tmp_path):
        import importlib

        groups_path = tmp_path / "groups.json"
        groups_path.write_text(json.dumps({"123": "trip-123"}))
        monkeypatch.setenv("ADMIN_TELEGRAM_USER_ID", "777")
        monkeypatch.setenv("GROUPS_JSON_PATH", str(groups_path))
        monkeypatch.delenv("ALLOWED_CHAT_ID", raising=False)
        monkeypatch.delenv("ALLOWED_USER_ID", raising=False)

        import config
        import telegram_bot.access as helpers

        importlib.reload(config)
        importlib.reload(helpers)

        update = _make_update(chat_id="123", user_id=42)
        assert helpers.is_allowed_chat(update)

    def test_others_cannot_talk_outside_allowed_group(self, monkeypatch, tmp_path):
        import importlib

        groups_path = tmp_path / "groups.json"
        groups_path.write_text(json.dumps({"123": "trip-123"}))
        monkeypatch.setenv("ADMIN_TELEGRAM_USER_ID", "777")
        monkeypatch.setenv("GROUPS_JSON_PATH", str(groups_path))
        monkeypatch.delenv("ALLOWED_CHAT_ID", raising=False)
        monkeypatch.delenv("ALLOWED_USER_ID", raising=False)

        import config
        import telegram_bot.access as helpers

        importlib.reload(config)
        importlib.reload(helpers)

        update = _make_update(chat_id="999", user_id=42)
        assert not helpers.is_allowed_chat(update)


class TestRegistryLoading:
    def test_logs_invalid_json_registry_file(self, caplog, tmp_path):
        from domain.registry import GroupRegistry

        groups_path = tmp_path / "groups.json"
        groups_path.write_text("{not json}")

        caplog.set_level(logging.WARNING, logger="domain.registry")
        registry = GroupRegistry.load(str(groups_path))

        assert registry.allowed_chat_ids == []
        assert f"Invalid JSON in registry file {groups_path}" in caplog.text


class TestLatestCmd:
    @patch("telegram_bot.commands.gateway.activities", return_value=FAKE_ACTIVITIES)
    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_shows_latest_activities(self, mock_resolve, mock_allowed, mock_get):
        from telegram_bot.commands import latest_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(latest_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert "Latest 3 activities" in text
        assert "Dinner" in text
        assert "Created expense" in text
        assert "Updated group" in text
        assert call_kwargs.kwargs.get("parse_mode") == "HTML"

    @patch("telegram_bot.commands.gateway.activities", return_value=[])
    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_no_expenses(self, mock_resolve, mock_allowed, mock_get):
        from telegram_bot.commands import latest_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(latest_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "No activity found."

    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_invalid_count(self, mock_resolve, mock_allowed):
        from telegram_bot.commands import latest_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["abc"]
        asyncio.run(latest_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args.args[0]
        assert text == "Count must be a positive integer."

    @patch("telegram_bot.commands.is_allowed_chat", return_value=False)
    def test_disallowed_chat(self, mock_allowed):
        from telegram_bot.commands import latest_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(latest_cmd(update, ctx))

        update.message.reply_text.assert_not_called()


class TestUndoCmd:
    @patch("telegram_bot.commands.gateway.activities", return_value=FAKE_ACTIVITIES)
    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_shows_latest_activity(self, mock_resolve, mock_allowed, mock_get):
        from telegram_bot.commands import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert "Dinner" in text
        assert "Undo activity #1?" in text

    @patch("telegram_bot.commands.gateway.activities", return_value=[])
    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_no_expenses(self, mock_resolve, mock_allowed, mock_get):
        from telegram_bot.commands import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "No activity found."

    @patch("telegram_bot.commands.gateway.activities", return_value=FAKE_ACTIVITIES[:2])
    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_non_undoable_activity(self, mock_resolve, mock_allowed, mock_get):
        from telegram_bot.commands import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["2"]
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args.args[0]
        assert text == "This activity can't be undone. Only newly created expenses can be undone."

    @patch("telegram_bot.commands.is_allowed_chat", return_value=False)
    def test_disallowed_chat(self, mock_allowed):
        from telegram_bot.commands import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_not_called()


class TestUndoButton:
    @patch("telegram_bot.callbacks.gateway.delete_expense")
    def test_confirm_delete(self, mock_delete):
        from telegram_bot.callbacks import button

        update = _make_callback_update("delyes_42_999")
        ctx = MagicMock()
        ctx.bot_data = {
            "pending_actions": {
                "42_999": PendingDelete(expense_id="exp-123", group_id="test-group-id")
            }
        }
        asyncio.run(button(update, ctx))

        mock_delete.assert_called_once_with("test-group-id", "exp-123")
        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Deleted."

    def test_cancel_delete(self):
        from telegram_bot.callbacks import button

        update = _make_callback_update("delno_42_999")
        ctx = MagicMock()
        ctx.bot_data = {
            "pending_actions": {
                "42_999": PendingDelete(expense_id="exp-123", group_id="test-group-id")
            }
        }
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Cancelled."

    def test_expired_delete(self):
        from telegram_bot.callbacks import button

        update = _make_callback_update("delyes_42_999")
        ctx = MagicMock()
        ctx.bot_data = {"pending_actions": {}}
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Expired. Try again."


class TestSettleCmd:
    @patch("telegram_bot.commands.gateway.group")
    @patch("telegram_bot.commands.gateway.balances", return_value=FAKE_BALANCES)
    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_shows_suggested_reimbursements(self, mock_resolve, mock_allowed, mock_get, mock_group):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo", "pid-3": "Yoga"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2", "yoga": "pid-3"},
                currency="$",
            ),
        )
        from telegram_bot.commands import settle_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(settle_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        markup = call_kwargs.kwargs.get("reply_markup")
        assert "Suggested reimbursements" in text
        assert "Baggie" in text
        assert "Neo" in text
        assert "$12.50" in text
        assert markup.inline_keyboard[0][0].callback_data == "settle_42_999_0"
        assert markup.inline_keyboard[-1][0].callback_data == "settleno_42_999"

    @patch(
        "telegram_bot.commands.gateway.balances",
        return_value=BalanceReport(balances=[], reimbursements=[]),
    )
    @patch(
        "telegram_bot.commands.gateway.group",
        return_value=Group(
            "Trip", "$", ParticipantDirectory(id_to_name={}, name_to_id={}, currency="$")
        ),
    )
    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    @patch("telegram_bot.group_picker.resolve_group", return_value="test-group-id")
    def test_no_reimbursements(self, mock_resolve, mock_allowed, mock_group, mock_get):
        from telegram_bot.commands import settle_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(settle_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "No suggested reimbursements."


class TestSettleButton:
    @patch(
        "telegram_bot.callbacks.gateway.group",
        return_value=Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        ),
    )
    @patch("telegram_bot.callbacks.gateway.settle")
    def test_marks_reimbursement_paid(self, mock_settle, mock_group):
        from telegram_bot.callbacks import button

        update = _make_callback_update("settle_42_999_0")
        ctx = MagicMock()
        ctx.bot_data = {
            "pending_actions": {
                "42_999_0": PendingSettlement(
                    from_id="pid-1", to_id="pid-2", amount=1250, group_id="test-group-id"
                )
            }
        }
        asyncio.run(button(update, ctx))

        mock_settle.assert_called_once_with(
            "test-group-id",
            Settlement(from_id="pid-1", to_id="pid-2", amount_cents=1250),
        )
        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Marked as paid: Baggie -> Neo ($12.50)"

    def test_expired_settlement(self):
        from telegram_bot.callbacks import button

        update = _make_callback_update("settle_42_999_0")
        ctx = MagicMock()
        ctx.bot_data = {"pending_actions": {}}
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Expired. Try again."

    def test_cancel_settlement(self):
        from telegram_bot.callbacks import button

        update = _make_callback_update("settleno_42_999")
        ctx = MagicMock()
        ctx.bot_data = {
            "pending_actions": {
                "42_999_0": PendingSettlement(
                    from_id="pid-1", to_id="pid-2", amount=1250, group_id="group-a"
                ),
                "42_999_1": PendingSettlement(
                    from_id="pid-3", to_id="pid-2", amount=2500, group_id="group-a"
                ),
            }
        }
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Cancelled."


class TestGroupSelection:
    @patch("telegram_bot.add_flow.gateway.group")
    def test_select_group_resumes_add_flow(self, mock_group):
        from telegram_bot.add_flow import interactive_select_group
        from telegram_bot.constants import PAYER

        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        )

        update = _make_callback_update("selgrp_test-group", chat_type="private")
        ctx = MagicMock()
        ctx.user_data = {
            "pending_cmd": "add",
            "pending_cmd_text": "/add dinner, 50, baggie neo",
            "expense_title": "Old",
            "expense_amount": 99.0,
            "payer_id": "stale-payer",
            "payer_name": "Stale",
            "selected_payees": ["stale-payee"],
            "participants_map": {"Stale": "stale-payer"},
        }

        state = asyncio.run(interactive_select_group(update, ctx))

        assert state == PAYER
        update.callback_query.edit_message_text.assert_called_once_with("Group: Trip")
        update.callback_query.message.reply_text.assert_called_once()
        assert "Who paid?" in update.callback_query.message.reply_text.call_args.args[0]
        assert ctx.user_data["active_group"] == "test-group"

    @patch("telegram_bot.commands.is_allowed_chat", return_value=True)
    def test_switch_cmd_requires_dm(self, mock_allowed):
        from telegram_bot.commands import switch_cmd

        update = _make_update(chat_type="group", text="/switch")
        ctx = MagicMock()
        asyncio.run(switch_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        assert update.message.reply_text.call_args.args[0] == "Use /switch in a DM."


class TestTelegramAddCmd:
    @patch("telegram_bot.add_flow.is_allowed_chat", return_value=True)
    @patch("telegram_bot.add_flow.resolve_group")
    def test_plain_add_starts_interactive_flow(self, mock_resolve, mock_allowed):
        from telegram_bot.add_flow import add_cmd
        from telegram_bot.constants import TITLE

        mock_resolve.return_value = "test-group"
        update = _make_update(text="/add")
        ctx = MagicMock()
        ctx.user_data = {}

        state = asyncio.run(add_cmd(update, ctx))

        assert state == TITLE
        update.message.reply_text.assert_called_once()
        assert update.message.reply_text.call_args.args[0] == "Enter expense title:"

    @patch("telegram_bot.add_flow.is_allowed_chat", return_value=True)
    @patch("telegram_bot.add_flow.resolve_group")
    def test_add_with_bot_mention_starts_interactive_flow(self, mock_resolve, mock_allowed):
        from telegram_bot.add_flow import add_cmd
        from telegram_bot.constants import TITLE

        mock_resolve.return_value = "test-group"
        update = _make_update(text="/add@spliit_bot")
        ctx = MagicMock()
        ctx.user_data = {}

        state = asyncio.run(add_cmd(update, ctx))

        assert state == TITLE
        update.message.reply_text.assert_called_once()
        assert update.message.reply_text.call_args.args[0] == "Enter expense title:"


class TestCli:
    def test_parser_group(self):
        args = build_parser().parse_args(["group"])
        assert args.command == "group"

    def test_parser_balance(self):
        args = build_parser().parse_args(["balance"])
        assert args.command == "balance"

    def test_parser_latest(self):
        args = build_parser().parse_args(["latest", "2"])
        assert args.command == "latest"
        assert args.limit == 2

    def test_parser_add(self):
        args = build_parser().parse_args(
            ["add", "Dinner", "50", "--paid-by", "Baggie", "--with", "Baggie", "Neo"]
        )
        assert args.command == "add"
        assert args.title == "Dinner"
        assert args.amount == 50
        assert args.paid_by == "Baggie"
        assert args.participants == ["Baggie", "Neo"]
        assert args.date is None

    def test_parser_add_with_date(self):
        args = build_parser().parse_args(
            [
                "add",
                "Dinner",
                "50",
                "--date",
                "2026-04-07T21:21+08:00",
                "--paid-by",
                "Baggie",
                "--with",
                "Baggie",
                "Neo",
            ]
        )
        assert args.command == "add"
        assert args.date == "2026-04-07T21:21+08:00"

    def test_parser_global_spliit_group(self):
        args = build_parser().parse_args(["--spliit-group", "trip-123", "group"])
        assert args.command == "group"
        assert args.spliit_group == "trip-123"

    def test_group_cmd_requires_spliit_group(self, capsys):
        code = cli_group_cmd()

        captured = capsys.readouterr()
        assert code == 1
        assert "Missing required --spliit-group." in captured.err

    def test_parser_undo(self):
        args = build_parser().parse_args(["undo", "3", "--yes"])
        assert args.command == "undo"
        assert args.index == 3
        assert args.yes is True

    def test_parser_settle_list(self):
        args = build_parser().parse_args(["settle", "list"])
        assert args.command == "settle"
        assert args.settle_command == "list"

    def test_parser_settle_pay(self):
        args = build_parser().parse_args(["settle", "pay", "2", "--yes"])
        assert args.command == "settle"
        assert args.settle_command == "pay"
        assert args.index == 2
        assert args.yes is True

    @patch("cli.gateway.group")
    def test_group_cmd(self, mock_group, capsys):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        )

        code = cli_group_cmd("test-group")

        captured = capsys.readouterr()
        assert code == 0
        assert "Trip ($)" in captured.out
        assert "- Baggie" in captured.out
        assert "- Neo" in captured.out

    @patch("cli.gateway.group")
    @patch("cli.gateway.balances", return_value=FAKE_BALANCES)
    def test_balance_cmd(self, mock_balances, mock_group, capsys):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo", "pid-3": "Yoga"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2", "yoga": "pid-3"},
                currency="$",
            ),
        )

        code = cli_balance_cmd("test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_balances.assert_called_once_with("test-group")
        assert "Trip balances" in captured.out
        assert "Suggested payments:" in captured.out
        assert "Baggie -> Neo: $12.50" in captured.out

    @patch("cli.gateway.activities", return_value=FAKE_ACTIVITIES[:1])
    def test_latest_cmd(self, mock_activities, capsys):
        code = cli_latest_cmd(1, "test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_activities.assert_called_once_with("test-group", 1)
        assert "Latest 1 activities" in captured.out
        assert "Dinner" in captured.out
        assert "Created expense" in captured.out

    @patch("cli.gateway.group")
    @patch("cli.gateway.create_expense")
    def test_add_cmd(self, mock_create_expense, mock_group, capsys):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        )

        code = cli_add_cmd("Dinner", 50, "Baggie", ["Baggie", "Neo"], "test-group")

        captured = capsys.readouterr()
        assert code == 0
        assert mock_create_expense.call_args.args[0] == "test-group"
        expense = mock_create_expense.call_args.args[1]
        assert expense == NewExpense(
            title="[cli] Dinner",
            paid_by="pid-1",
            paid_for=[("pid-1", 1), ("pid-2", 1)],
            amount_cents=5000,
            expense_date=None,
        )
        assert "Added: Dinner" in captured.out
        assert "Split ($25.00 each): Baggie, Neo" in captured.out

    @patch("cli.gateway.group")
    @patch("cli.gateway.create_expense")
    def test_add_cmd_with_date(self, mock_create_expense, mock_group, capsys):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        )

        code = cli_add_cmd(
            "Dinner",
            50,
            "Baggie",
            ["Baggie", "Neo"],
            "test-group",
            expense_date="2026-04-07T21:21+08:00",
        )

        captured = capsys.readouterr()
        assert code == 0
        assert mock_create_expense.call_args.args[0] == "test-group"
        expense = mock_create_expense.call_args.args[1]
        assert expense == NewExpense(
            title="[cli] Dinner",
            paid_by="pid-1",
            paid_for=[("pid-1", 1), ("pid-2", 1)],
            amount_cents=5000,
            expense_date="2026-04-07T13:21:00.000Z",
        )
        assert "Date: 2026-04-07T21:21+08:00" in captured.out

    @patch("cli.gateway.group")
    @patch("cli.gateway.create_expense")
    def test_add_cmd_with_invalid_date(self, mock_create_expense, mock_group, capsys):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        )

        code = cli_add_cmd(
            "Dinner",
            50,
            "Baggie",
            ["Baggie", "Neo"],
            "test-group",
            expense_date="not-a-date",
        )

        captured = capsys.readouterr()
        assert code == 1
        mock_create_expense.assert_not_called()
        assert "Invalid --date." in captured.err

    @patch("cli.gateway.activities", return_value=FAKE_ACTIVITIES[:1])
    @patch("cli.gateway.delete_expense")
    def test_undo_cmd(self, mock_delete, mock_activities, capsys):
        code = cli_undo_cmd(1, assume_yes=True, group_id="test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_delete.assert_called_once_with("test-group", "exp-123")
        assert "Undid:" in captured.out
        assert "Dinner" in captured.out

    @patch("cli.gateway.group")
    @patch(
        "cli.gateway.balances",
        return_value=BalanceReport(
            balances=[],
            reimbursements=[Reimbursement(from_id="pid-1", to_id="pid-2", amount_cents=1250)],
        ),
    )
    def test_list_reimbursements(self, mock_balances, mock_group, capsys):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        )
        code = list_reimbursements("test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_balances.assert_called_once_with("test-group")
        assert "1. Baggie -> Neo ($12.50)" in captured.out

    @patch("cli.gateway.group")
    @patch(
        "cli.gateway.balances",
        return_value=BalanceReport(
            balances=[],
            reimbursements=[Reimbursement(from_id="pid-1", to_id="pid-2", amount_cents=1250)],
        ),
    )
    @patch("cli.gateway.settle")
    def test_mark_reimbursement_paid(self, mock_settle, mock_balances, mock_group, capsys):
        mock_group.return_value = Group(
            "Trip",
            "$",
            ParticipantDirectory(
                id_to_name={"pid-1": "Baggie", "pid-2": "Neo"},
                name_to_id={"baggie": "pid-1", "neo": "pid-2"},
                currency="$",
            ),
        )
        code = mark_reimbursement_paid(1, assume_yes=True, group_id="test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_settle.assert_called_once_with(
            "test-group", Settlement(from_id="pid-1", to_id="pid-2", amount_cents=1250)
        )
        assert "Marked as paid: Baggie -> Neo ($12.50)" in captured.out


class TestHealthHttp:
    def test_up_returns_200(self) -> None:
        from infra.health_http import start_background_health_server

        server = start_background_health_server(0)
        try:
            url = f"http://127.0.0.1:{server.server_port}/up"
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert resp.status == 200
                assert resp.read() == b"ok\n"
        finally:
            server.shutdown()
            server.server_close()

    def test_other_paths_404(self) -> None:
        from infra.health_http import start_background_health_server

        server = start_background_health_server(0)
        try:
            url = f"http://127.0.0.1:{server.server_port}/nope"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)
            assert exc_info.value.code == 404
        finally:
            server.shutdown()
            server.server_close()


SPLIT_PIDS = ["a", "b", "c"]
SPLIT_NAMES = ["Alice", "Bob", "Carol"]


class TestParseSplitValues:
    def test_shares_ok(self):
        paid_for, err = parse_split_values(
            "2 1 1", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_SHARES, amount_cents=4000
        )
        assert err is None
        assert paid_for == [("a", 2), ("b", 1), ("c", 1)]

    def test_shares_comma_separated(self):
        paid_for, err = parse_split_values(
            "2, 1, 1", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_SHARES, amount_cents=4000
        )
        assert err is None
        assert paid_for == [("a", 2), ("b", 1), ("c", 1)]

    def test_shares_wrong_count(self):
        paid_for, err = parse_split_values(
            "2 1", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_SHARES, amount_cents=4000
        )
        assert paid_for == []
        assert err is not None and "Expected 3" in err

    def test_shares_non_integer(self):
        _, err = parse_split_values(
            "2 1.5 1", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_SHARES, amount_cents=4000
        )
        assert err is not None and "not a whole number" in err

    def test_shares_zero_rejected(self):
        _, err = parse_split_values(
            "2 0 1", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_SHARES, amount_cents=4000
        )
        assert err is not None and "positive" in err

    def test_percentage_ok(self):
        paid_for, err = parse_split_values(
            "50 30 20", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_PERCENTAGE, amount_cents=10000
        )
        assert err is None
        assert paid_for == [("a", 5000), ("b", 3000), ("c", 2000)]

    def test_percentage_must_sum_to_100(self):
        _, err = parse_split_values(
            "50 30 30", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_PERCENTAGE, amount_cents=10000
        )
        assert err is not None and "sum to 100" in err

    def test_amount_ok(self):
        paid_for, err = parse_split_values(
            "20 15 5", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_AMOUNT, amount_cents=4000
        )
        assert err is None
        assert paid_for == [("a", 2000), ("b", 1500), ("c", 500)]

    def test_amount_must_match_total(self):
        _, err = parse_split_values(
            "20 15 4", SPLIT_PIDS, SPLIT_NAMES, SplitMode.BY_AMOUNT, amount_cents=4000
        )
        assert err is not None and "sum to 40.00" in err


class TestCreateExpenseSplitMode:
    @patch("spliit_integration.gateway.get_current_timestamp", return_value="now")
    @patch("spliit_integration.gateway.trpc_post")
    def test_evenly_default(self, mock_post, mock_now):
        from spliit_integration.gateway import gateway

        gateway.create_expense(
            "g",
            NewExpense(
                title="t",
                paid_by="p1",
                paid_for=[("p1", 1), ("p2", 1)],
                amount_cents=4000,
            ),
        )
        payload = mock_post.call_args.args[1]
        assert payload["expenseFormValues"]["splitMode"] == SplitMode.EVENLY.value

    @patch("spliit_integration.gateway.get_current_timestamp", return_value="now")
    @patch("spliit_integration.gateway.trpc_post")
    def test_by_shares(self, mock_post, mock_now):
        from spliit_integration.gateway import gateway

        gateway.create_expense(
            "g",
            NewExpense(
                title="t",
                paid_by="p1",
                paid_for=[("p1", 2), ("p2", 1)],
                amount_cents=4000,
                split_mode=SplitMode.BY_SHARES,
            ),
        )
        payload = mock_post.call_args.args[1]
        assert payload["expenseFormValues"]["splitMode"] == SplitMode.BY_SHARES.value
        assert payload["expenseFormValues"]["paidFor"] == [
            {"participant": "p1", "shares": 2},
            {"participant": "p2", "shares": 1},
        ]

    @patch("spliit_integration.gateway.get_current_timestamp", return_value="now")
    @patch("spliit_integration.gateway.trpc_post")
    def test_by_percentage(self, mock_post, mock_now):
        from spliit_integration.gateway import gateway

        gateway.create_expense(
            "g",
            NewExpense(
                title="t",
                paid_by="p1",
                paid_for=[("p1", 5000), ("p2", 5000)],
                amount_cents=4000,
                split_mode=SplitMode.BY_PERCENTAGE,
            ),
        )
        payload = mock_post.call_args.args[1]
        assert payload["expenseFormValues"]["splitMode"] == SplitMode.BY_PERCENTAGE.value

    @patch("spliit_integration.gateway.get_current_timestamp", return_value="now")
    @patch("spliit_integration.gateway.trpc_post")
    def test_by_amount(self, mock_post, mock_now):
        from spliit_integration.gateway import gateway

        gateway.create_expense(
            "g",
            NewExpense(
                title="t",
                paid_by="p1",
                paid_for=[("p1", 2500), ("p2", 1500)],
                amount_cents=4000,
                split_mode=SplitMode.BY_AMOUNT,
            ),
        )
        payload = mock_post.call_args.args[1]
        assert payload["expenseFormValues"]["splitMode"] == SplitMode.BY_AMOUNT.value
