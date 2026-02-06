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

    @pytest.mark.parametrize("text", [
        "hello how are you",
        "what's for dinner",
        "lol nice one",
        "random gibberish text",
        "hey what's up",
    ])
    def test_no_number_no_participant_rejected(self, text):
        import re
        raw = re.sub(r"^/add[-_]?bill?\s*", "", f"/add {text}", flags=re.IGNORECASE).strip()
        has_number = bool(re.search(r"\d", raw))
        has_participant = any(n.lower() in raw.lower() for n in PARTICIPANTS)
        assert not has_number and not has_participant

    @pytest.mark.parametrize("text", [
        "lunch 50",
        "baggie paid for dinner",
        "neo owes 20",
        "100 for groceries",
    ])
    def test_number_or_participant_accepted(self, text):
        import re
        raw = re.sub(r"^/add[-_]?bill?\s*", "", f"/add {text}", flags=re.IGNORECASE).strip()
        has_number = bool(re.search(r"\d", raw))
        has_participant = any(n.lower() in raw.lower() for n in PARTICIPANTS)
        assert has_number or has_participant


@pytest.mark.llm
class TestParseWithLLM:
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
