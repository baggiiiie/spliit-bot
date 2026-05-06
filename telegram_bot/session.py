from __future__ import annotations

from dataclasses import dataclass

from domain.expense import ExpenseDraft, PendingExpense

ACTIVE_GROUP_KEY = "active_group"
PENDING_CMD_KEY = "pending_cmd"
PENDING_CMD_TEXT_KEY = "pending_cmd_text"
ADD_PENDING_CMD = "add"
DRAFT_KEY = "expense_draft"
PENDING_ACTIONS_KEY = "pending_actions"


@dataclass(slots=True)
class PendingDelete:
    expense_id: str
    group_id: str


@dataclass(slots=True)
class PendingSettlement:
    from_id: str
    to_id: str
    amount: int
    group_id: str


PendingAction = PendingExpense | PendingDelete | PendingSettlement


class Session:
    def __init__(self, user_data: dict | None, bot_data: dict | None = None) -> None:
        self.user_data = user_data if isinstance(user_data, dict) else {}
        self.bot_data = bot_data if isinstance(bot_data, dict) else {}

    @property
    def active_group_id(self) -> str | None:
        active_group = self.user_data.get(ACTIVE_GROUP_KEY)
        return str(active_group) if active_group else None

    @active_group_id.setter
    def active_group_id(self, group_id: str | None) -> None:
        if group_id is None:
            self.user_data.pop(ACTIVE_GROUP_KEY, None)
        else:
            self.user_data[ACTIVE_GROUP_KEY] = group_id

    @property
    def pending_add_text(self) -> str | None:
        pending_cmd = self.user_data.get(PENDING_CMD_KEY)
        pending_text = self.user_data.get(PENDING_CMD_TEXT_KEY)
        if pending_cmd != ADD_PENDING_CMD:
            return None
        return str(pending_text) if pending_text else "/add"

    @pending_add_text.setter
    def pending_add_text(self, text: str | None) -> None:
        if text is None:
            self.user_data.pop(PENDING_CMD_KEY, None)
            self.user_data.pop(PENDING_CMD_TEXT_KEY, None)
        else:
            self.user_data[PENDING_CMD_KEY] = ADD_PENDING_CMD
            self.user_data[PENDING_CMD_TEXT_KEY] = text

    def pop_pending_add_text(self) -> str | None:
        text = self.pending_add_text
        self.pending_add_text = None
        return text

    @property
    def draft(self) -> ExpenseDraft | None:
        draft = self.user_data.get(DRAFT_KEY)
        return draft if isinstance(draft, ExpenseDraft) else None

    @draft.setter
    def draft(self, draft: ExpenseDraft | None) -> None:
        if draft is None:
            self.user_data.pop(DRAFT_KEY, None)
        else:
            self.user_data[DRAFT_KEY] = draft

    def _actions(self) -> dict[str, PendingAction]:
        actions = self.bot_data.setdefault(PENDING_ACTIONS_KEY, {})
        assert isinstance(actions, dict)
        return actions

    def stash(self, key: str, action: PendingAction) -> str:
        self._actions()[key] = action
        return key

    def pop(self, key: str) -> PendingAction | None:
        return self._actions().pop(key, None)

    def cancel_with_prefix(self, prefix: str) -> None:
        actions = self._actions()
        for key in list(actions):
            if key.startswith(prefix):
                actions.pop(key, None)
