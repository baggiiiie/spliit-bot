from bot import ParsedExpense, parse_add_command

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
        assert result == ParsedExpense(title="dinner", amount=50.0)
        assert result.participants is None

    def test_case_insensitive_names(self):
        result = parse_add_command("/add dinner, 50, BAGGIE Neo", PARTICIPANTS)
        assert result is not None
        assert result.participants == ["baggie", "neo"]

    def test_names_without_known_participants(self):
        result = parse_add_command("/add dinner, 50, baggie neo")
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
