import asyncio
import json
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
        result, _ = parse_with_llm("dinner cost 100 split between baggie and neo", PARTICIPANTS)
        assert isinstance(result, ParsedExpense)
        assert result.amount == 100.0
        assert result.participants is not None
        assert "baggie" in result.participants
        assert "neo" in result.participants

    def test_all_participants(self):
        result, _ = parse_with_llm("lunch 50 everyone splits", PARTICIPANTS)
        assert isinstance(result, ParsedExpense)
        assert result.amount == 50.0
        assert result.participants is not None
        assert len(result.participants) == 4

    def test_nonsense_returns_error(self):
        result, _ = parse_with_llm("hello how are you", PARTICIPANTS)
        assert result is None or isinstance(result, str)


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
    {
        "id": "act-1",
        "activityType": "CREATE_EXPENSE",
        "expenseId": "exp-123",
        "data": "Dinner",
        "expense": FAKE_EXPENSES[0],
    },
    {
        "id": "act-2",
        "activityType": "UPDATE_GROUP",
        "expenseId": None,
        "data": None,
        "expense": None,
    },
    {
        "id": "act-3",
        "activityType": "DELETE_EXPENSE",
        "expenseId": "exp-deleted",
        "data": "Taxi",
        "expense": None,
    },
]

FAKE_BALANCES = {
    "balances": {},
    "reimbursements": [
        {"from": "pid-1", "to": "pid-2", "amount": 1250},
        {"from": "pid-3", "to": "pid-2", "amount": 2500},
    ],
}


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
        import helpers

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
        import helpers

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
        import helpers

        importlib.reload(config)
        importlib.reload(helpers)

        update = _make_update(chat_id="999", user_id=42)
        assert not helpers.is_allowed_chat(update)


class TestLatestCmd:
    @patch("handlers.id_to_name_map", return_value=({}, "$"))
    @patch("handlers.get_activities", return_value=FAKE_ACTIVITIES)
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_shows_latest_activities(self, mock_resolve, mock_allowed, mock_get, mock_idname):
        from handlers import latest_cmd

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

    @patch("handlers.id_to_name_map", return_value=({}, "$"))
    @patch("handlers.get_activities", return_value=[])
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_no_expenses(self, mock_resolve, mock_allowed, mock_get, mock_idname):
        from handlers import latest_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(latest_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "No activity found."

    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_invalid_count(self, mock_resolve, mock_allowed):
        from handlers import latest_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["abc"]
        asyncio.run(latest_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args.args[0]
        assert text == "Count must be a positive integer."

    @patch("handlers.is_allowed_chat", return_value=False)
    def test_disallowed_chat(self, mock_allowed):
        from handlers import latest_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(latest_cmd(update, ctx))

        update.message.reply_text.assert_not_called()


class TestUndoCmd:
    @patch("handlers.get_activities", return_value=FAKE_ACTIVITIES)
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_shows_latest_activity(self, mock_resolve, mock_allowed, mock_get):
        from handlers import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert "Dinner" in text
        assert "Undo activity #1?" in text

    @patch("handlers.get_activities", return_value=[])
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_no_expenses(self, mock_resolve, mock_allowed, mock_get):
        from handlers import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "No activity found."

    @patch("handlers.get_activities", return_value=FAKE_ACTIVITIES[:2])
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_non_undoable_activity(self, mock_resolve, mock_allowed, mock_get):
        from handlers import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = ["2"]
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args.args[0]
        assert text == "This activity can't be undone. Only newly created expenses can be undone."

    @patch("handlers.is_allowed_chat", return_value=False)
    def test_disallowed_chat(self, mock_allowed):
        from handlers import undo_cmd

        update = _make_update()
        ctx = MagicMock()
        ctx.args = []
        asyncio.run(undo_cmd(update, ctx))

        update.message.reply_text.assert_not_called()


class TestUndoButton:
    @patch("handlers.delete_expense")
    @patch("handlers.pending_deletes", {"42_999": ("exp-123", "test-group-id")})
    def test_confirm_delete(self, mock_delete):
        from handlers import button

        update = _make_callback_update("delyes_42_999")
        ctx = MagicMock()
        asyncio.run(button(update, ctx))

        mock_delete.assert_called_once_with("test-group-id", "exp-123")
        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Deleted."

    @patch("handlers.pending_deletes", {"42_999": ("exp-123", "test-group-id")})
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


class TestSettleCmd:
    @patch(
        "handlers.id_to_name_map",
        return_value=({"pid-1": "Baggie", "pid-2": "Neo", "pid-3": "Yoga"}, "$"),
    )
    @patch("handlers.get_balances", return_value=FAKE_BALANCES)
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_shows_suggested_reimbursements(
        self, mock_resolve, mock_allowed, mock_get, mock_idname
    ):
        from handlers import settle_cmd

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

    @patch("handlers.get_balances", return_value={"balances": {}, "reimbursements": []})
    @patch("handlers.id_to_name_map", return_value=({}, "$"))
    @patch("handlers.is_allowed_chat", return_value=True)
    @patch("handlers.resolve_group", return_value=("test-group-id", MagicMock()))
    def test_no_reimbursements(self, mock_resolve, mock_allowed, mock_idname, mock_get):
        from handlers import settle_cmd

        update = _make_update()
        ctx = MagicMock()
        asyncio.run(settle_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "No suggested reimbursements."


class TestSettleButton:
    @patch(
        "handlers.id_to_name_map",
        return_value=({"pid-1": "Baggie", "pid-2": "Neo"}, "$"),
    )
    @patch("handlers.settle_reimbursement")
    @patch("handlers.get_spliit", return_value=MagicMock())
    @patch(
        "handlers.pending_settlements",
        {"42_999_0": ("pid-1", "pid-2", 1250, "test-group-id")},
    )
    def test_marks_reimbursement_paid(self, mock_get_spliit, mock_settle, mock_idname):
        from handlers import button

        update = _make_callback_update("settle_42_999_0")
        ctx = MagicMock()
        asyncio.run(button(update, ctx))

        mock_get_spliit.assert_called_once_with("test-group-id")
        mock_settle.assert_called_once_with("test-group-id", "pid-1", "pid-2", 1250)
        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Marked as paid: Baggie -> Neo ($12.50)"

    @patch("handlers.pending_settlements", {})
    def test_expired_settlement(self):
        from handlers import button

        update = _make_callback_update("settle_42_999_0")
        ctx = MagicMock()
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Expired. Try again."

    @patch(
        "handlers.pending_settlements",
        {
            "42_999_0": ("pid-1", "pid-2", 1250, "group-a"),
            "42_999_1": ("pid-3", "pid-2", 2500, "group-a"),
        },
    )
    def test_cancel_settlement(self):
        from handlers import button

        update = _make_callback_update("settleno_42_999")
        ctx = MagicMock()
        asyncio.run(button(update, ctx))

        update.callback_query.message.reply_text.assert_called_once()
        call_kwargs = update.callback_query.message.reply_text.call_args
        text = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("text", "")
        assert text == "Cancelled."


class TestGroupSelection:
    @patch("handlers.get_spliit")
    def test_select_group_resumes_add_flow(self, mock_get_spliit):
        from handlers import PAYER, interactive_select_group

        client = MagicMock()
        client.get_group.return_value = {"name": "Trip"}
        client.get_participants.return_value = {"Baggie": "pid-1", "Neo": "pid-2"}
        mock_get_spliit.return_value = client

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

    @patch("handlers.is_allowed_chat", return_value=True)
    def test_switch_cmd_requires_dm(self, mock_allowed):
        from handlers import switch_cmd

        update = _make_update(chat_type="group", text="/switch")
        ctx = MagicMock()
        asyncio.run(switch_cmd(update, ctx))

        update.message.reply_text.assert_called_once()
        assert update.message.reply_text.call_args.args[0] == "Use /switch in a DM."


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

    @patch("cli.get_spliit")
    def test_group_cmd(self, mock_get_spliit, capsys):
        client = MagicMock()
        client.get_group.return_value = {
            "name": "Trip",
            "currency": "$",
            "participants": [{"name": "Baggie"}, {"name": "Neo"}],
        }
        mock_get_spliit.return_value = client

        code = cli_group_cmd("test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_get_spliit.assert_called_once_with("test-group")
        assert "Trip ($)" in captured.out
        assert "- Baggie" in captured.out
        assert "- Neo" in captured.out

    @patch(
        "cli.id_to_name_map",
        return_value=(
            {"pid-1": "Baggie", "pid-2": "Neo", "pid-3": "Yoga"},
            "$",
        ),
    )
    @patch("cli.get_balances", return_value=FAKE_BALANCES)
    @patch("cli.get_spliit")
    def test_balance_cmd(self, mock_get_spliit, mock_get, mock_idname, capsys):
        client = MagicMock()
        client.get_group.return_value = {"name": "Trip"}
        mock_get_spliit.return_value = client

        code = cli_balance_cmd("test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_get.assert_called_once_with("test-group")
        assert "Trip balances" in captured.out
        assert "Suggested payments:" in captured.out
        assert "Baggie -> Neo: $12.50" in captured.out

    @patch("cli.get_activities", return_value=FAKE_ACTIVITIES[:1])
    @patch("cli.get_spliit", return_value=MagicMock())
    def test_latest_cmd(self, mock_get_spliit, mock_get, capsys):
        code = cli_latest_cmd(1, "test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_get.assert_called_once_with("test-group", 1)
        assert "Latest 1 activities" in captured.out
        assert "Dinner" in captured.out
        assert "Created expense" in captured.out

    @patch("cli.id_to_name_map", return_value=({"pid-1": "Baggie", "pid-2": "Neo"}, "$"))
    @patch("cli.create_expense")
    @patch("cli.get_spliit")
    def test_add_cmd(self, mock_get_spliit, mock_create_expense, mock_idname, capsys):
        client = MagicMock()
        mock_get_spliit.return_value = client

        code = cli_add_cmd("Dinner", 50, "Baggie", ["Baggie", "Neo"], "test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_create_expense.assert_called_once_with(
            group_id="test-group",
            title="[cli] Dinner",
            paid_by="pid-1",
            paid_for=[("pid-1", 1), ("pid-2", 1)],
            amount=5000,
            expense_date=None,
        )
        assert "Added: Dinner" in captured.out
        assert "Split ($25.00 each): Baggie, Neo" in captured.out

    @patch("cli.id_to_name_map", return_value=({"pid-1": "Baggie", "pid-2": "Neo"}, "$"))
    @patch("cli.create_expense")
    @patch("cli.get_spliit")
    def test_add_cmd_with_date(self, mock_get_spliit, mock_create_expense, mock_idname, capsys):
        client = MagicMock()
        mock_get_spliit.return_value = client

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
        mock_create_expense.assert_called_once_with(
            group_id="test-group",
            title="[cli] Dinner",
            paid_by="pid-1",
            paid_for=[("pid-1", 1), ("pid-2", 1)],
            amount=5000,
            expense_date="2026-04-07T13:21:00.000Z",
        )
        assert "Date: 2026-04-07T21:21+08:00" in captured.out

    @patch("cli.id_to_name_map", return_value=({"pid-1": "Baggie", "pid-2": "Neo"}, "$"))
    @patch("cli.create_expense")
    @patch("cli.get_spliit")
    def test_add_cmd_with_invalid_date(
        self, mock_get_spliit, mock_create_expense, mock_idname, capsys
    ):
        client = MagicMock()
        mock_get_spliit.return_value = client

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

    @patch("cli.get_activities", return_value=FAKE_ACTIVITIES[:1])
    @patch("cli.delete_expense")
    @patch("cli.get_spliit", return_value=MagicMock())
    def test_undo_cmd(self, mock_get_spliit, mock_delete, mock_get, capsys):
        code = cli_undo_cmd(1, assume_yes=True, group_id="test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_delete.assert_called_once_with("test-group", "exp-123")
        assert "Undid:" in captured.out
        assert "Dinner" in captured.out

    @patch("cli.id_to_name_map", return_value=({"pid-1": "Baggie", "pid-2": "Neo"}, "$"))
    @patch(
        "cli.get_balances",
        return_value={"reimbursements": [{"from": "pid-1", "to": "pid-2", "amount": 1250}]},
    )
    @patch("cli.get_spliit", return_value=MagicMock())
    def test_list_reimbursements(self, mock_get_spliit, mock_get, mock_idname, capsys):
        code = list_reimbursements("test-group")

        captured = capsys.readouterr()
        assert code == 0
        assert "1. Baggie -> Neo ($12.50)" in captured.out

    @patch("cli.id_to_name_map", return_value=({"pid-1": "Baggie", "pid-2": "Neo"}, "$"))
    @patch(
        "cli.get_balances",
        return_value={"reimbursements": [{"from": "pid-1", "to": "pid-2", "amount": 1250}]},
    )
    @patch("cli.settle_reimbursement")
    @patch("cli.get_spliit", return_value=MagicMock())
    def test_mark_reimbursement_paid(
        self, mock_get_spliit, mock_settle, mock_get, mock_idname, capsys
    ):
        code = mark_reimbursement_paid(1, assume_yes=True, group_id="test-group")

        captured = capsys.readouterr()
        assert code == 0
        mock_settle.assert_called_once_with("test-group", "pid-1", "pid-2", 1250)
        assert "Marked as paid: Baggie -> Neo ($12.50)" in captured.out


class TestHealthHttp:
    def test_up_returns_200(self) -> None:
        from health_http import start_background_health_server

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
        from health_http import start_background_health_server

        server = start_background_health_server(0)
        try:
            url = f"http://127.0.0.1:{server.server_port}/nope"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)
            assert exc_info.value.code == 404
        finally:
            server.shutdown()
            server.server_close()
