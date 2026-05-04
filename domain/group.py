from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class Participant:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ParticipantDirectory:
    id_to_name: dict[str, str]
    name_to_id: dict[str, str]
    currency: str

    def participant_id(self, name: str) -> str | None:
        return self.name_to_id.get(name.lower())

    def participant_name(self, participant_id: str) -> str:
        return self.id_to_name.get(participant_id, participant_id)

    def unknown_names(self, names: list[str]) -> list[str]:
        return [name for name in names if not self.participant_id(name)]

    def participant_ids(self, names: list[str]) -> list[str]:
        ids: list[str] = []
        for name in names:
            participant_id = self.participant_id(name)
            assert participant_id is not None
            ids.append(participant_id)
        return ids

    @property
    def participants(self) -> list[Participant]:
        return [Participant(id=pid, name=name) for pid, name in self.id_to_name.items()]

    @property
    def participants_map(self) -> dict[str, str]:
        return {participant.name: participant.id for participant in self.participants}


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    currency: str
    directory: ParticipantDirectory

    @classmethod
    def from_spliit_dict(cls, group: Mapping[str, object]) -> Group:
        participants = group["participants"]
        assert isinstance(participants, list)
        id_to_name: dict[str, str] = {}
        for participant in participants:
            if isinstance(participant, Mapping):
                participant_data = cast(Mapping[str, object], participant)
                participant_id = participant_data.get("id", "")
                participant_name = participant_data.get("name", "")
                id_to_name[str(participant_id)] = str(participant_name)
        currency = str(group["currency"])
        return cls(
            name=str(group["name"]),
            currency=currency,
            directory=ParticipantDirectory(
                id_to_name=id_to_name,
                name_to_id={name.lower(): pid for pid, name in id_to_name.items()},
                currency=currency,
            ),
        )
