from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_json_dict(path: str) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        logger.warning("Registry file not found: %s", path)
        return {}
    except json.JSONDecodeError as error:
        logger.warning("Invalid JSON in registry file %s: %s", path, error)
        return {}
    except OSError as error:
        logger.warning("Failed to read registry file %s: %s", path, error)
        return {}

    if not isinstance(data, dict):
        logger.warning(
            "Expected JSON object in registry file %s, got %s",
            path,
            type(data).__name__,
        )
        return {}
    return {str(key): str(value) for key, value in data.items()}


@dataclass(frozen=True, slots=True)
class UserDirectory:
    spliit_to_telegram: dict[str, str]

    @classmethod
    def load(cls, path: str) -> UserDirectory:
        return cls(
            spliit_to_telegram={
                name.lower(): telegram_id for name, telegram_id in _load_json_dict(path).items()
            }
        )

    def telegram_id(self, participant_name: str) -> str | None:
        return self.spliit_to_telegram.get(participant_name.lower())


@dataclass(frozen=True, slots=True)
class GroupRegistry:
    chat_to_group: dict[str, str]

    @classmethod
    def load(cls, path: str) -> GroupRegistry:
        return cls(chat_to_group=_load_json_dict(path))

    @property
    def allowed_chat_ids(self) -> list[str]:
        return list(self.chat_to_group)

    @property
    def all_group_ids(self) -> list[str]:
        return list(dict.fromkeys(self.chat_to_group.values()))

    def group_id(self, chat_id: str) -> str | None:
        return self.chat_to_group.get(chat_id)


@cache
def load_user_directory(path: str) -> UserDirectory:
    return UserDirectory.load(path)


@cache
def load_group_registry(path: str) -> GroupRegistry:
    return GroupRegistry.load(path)
