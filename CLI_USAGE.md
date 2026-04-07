# Spliit CLI Usage

This project includes a local CLI for working with a Spliit group without Telegram.

## Run the CLI

Preferred command:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> <command>
```

If the script entrypoint is not available in your environment, run:

```bash
uv run python cli.py --spliit-group <GROUP_ID> <command>
```

Example group ID from a Spliit URL:

```text
https://spliit.app/groups/<GROUP_ID>/balances
```

## Common commands

Show group participants:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> group
```

Show balances and suggested reimbursements:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> balance
```

Show latest activities:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> latest
uv run spliit-cli --spliit-group <GROUP_ID> latest 10
```

## Add an expense

Syntax:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> add "<TITLE>" <AMOUNT> --paid-by <NAME> --with <NAME> <NAME> ...
```

With an explicit expense date/time:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> add "<TITLE>" <AMOUNT> --date "<ISO_DATETIME>" --paid-by <NAME> --with <NAME> <NAME> ...
```

Notes:
- `AMOUNT` is in the group currency.
- `--paid-by` must match a participant name exactly.
- `--with` lists everyone included in the split.
- `--date` accepts ISO 8601, for example:
  - `2026-04-07`
  - `2026-04-07T21:21`
  - `2026-04-07T21:21+08:00`
- If `--date` is omitted, the current time is used.
- Naive dates/times without a timezone are treated as UTC.
- The CLI adds expenses with a `[cli]` prefix in Spliit.

Example:

```bash
uv run spliit-cli --spliit-group yhA8ZtYsoX0AAK9k9RvZ- add "GRAB RIDES-EC" 20.6 --date "2026-04-07T21:21+08:00" --paid-by Yingchao --with Yingchao Lincan
```

## Undo a recent expense

Undo the latest undoable activity:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> undo
```

Undo a specific activity from `latest`:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> undo 3
```

Skip confirmation:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> undo 3 --yes
```

## Reimbursements

List suggested reimbursements:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> settle list
```

Mark a reimbursement as paid:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> settle pay 1
```

Skip confirmation:

```bash
uv run spliit-cli --spliit-group <GROUP_ID> settle pay 1 --yes
```

## Typical workflow

```bash
uv run spliit-cli --spliit-group <GROUP_ID> group
uv run spliit-cli --spliit-group <GROUP_ID> add "Dinner" 50 --paid-by Alice --with Alice Bob
uv run spliit-cli --spliit-group <GROUP_ID> balance
uv run spliit-cli --spliit-group <GROUP_ID> latest 5
```

## Troubleshooting

If you get an unknown participant error:
- Run `group` first.
- Use the participant names exactly as shown.

If `uv run spliit-cli` does not work in your shell:
- Use `uv run python cli.py ...` instead.
