# Context

## Glossary

### Expense draft
A partially-filled expense being assembled before it becomes a pending expense confirmation. It may be missing title, amount, payer, participants, split mode, or split values.

### Expense draft intake
The process that turns `/add` user input, callback selections, and LLM extraction results into progress on an expense draft. Expense draft intake decides what draft information was learned, what is still missing, and whether the user should be prompted, rejected, or shown a confirmation.

### Expense prompt
A Telegram message that asks the user for missing expense draft information. Expense prompts render title, amount, payer, payees, split mode, and split values requests from the current expense draft.

### Expense confirmation
The review step after expense draft intake has enough information to create a pending expense. Expense confirmation builds the message shown to the user and stores the pending expense that the confirm callback will submit to Spliit.

### Pending action
A short-lived Telegram callback action waiting for the user to confirm, cancel, or choose an item. Pending actions include expense confirmations, undo deletes, and settlement reimbursements.

### Callback response
The Telegram response sent after a user taps an inline button. Callback responses clear stale inline markup when possible and reply near the original callback message.

### Participant directory
The group participant lookup used by bot and CLI flows. It resolves Spliit participant ids to names, names to ids, and carries the group currency needed for display.

### Group selection
The process of choosing which configured Spliit group a Telegram DM or CLI command targets. Group selection labels configured groups for user-facing pickers and falls back to the raw group id when Spliit group metadata cannot be loaded.

### Group resolution
The Telegram command step that resolves an update and user session to a concrete Spliit group. Group resolution returns a Spliit client when possible and sends the appropriate no-group message when a command cannot proceed.

### Telegram keyboard
The inline buttons shown during Telegram flows. Telegram keyboards translate domain options such as participants, split modes, reimbursements, and configured groups into callback data.

### Expense receipt
The message sent after Spliit accepts a confirmed expense. It summarizes title, amount, payer, split details, and Telegram mentions for the involved participants.

### Telegram mention
The user-facing representation of a Spliit participant in Telegram messages. A Telegram mention prefers usernames, falls back to deep links for known Telegram ids, and leaves unknown participants as plain text.

### LLM error report
The admin-only Telegram notification sent when LLM expense extraction returns a user-visible parsing error. An LLM error report includes the raw input, user-facing error, and raw model response for debugging.

### Balance view
The user-facing summary of Spliit balances and suggested reimbursements. Balance views translate participant ids and cent amounts into display names and money strings for Telegram and CLI outputs.

### Expense date
The timestamp sent to Spliit when creating a dated expense. Expense dates accept ISO 8601 user input and are normalized to UTC millisecond timestamps.

### Command argument
A user-supplied Telegram or CLI argument parsed before a command can execute. Command arguments are validated at the command seam and return user-facing error text instead of throwing for normal bad input.

### CLI target
The Spliit group selected for a local CLI command. CLI target resolution requires `--spliit-group` and returns user-facing stderr text when the group id is missing.

### User session
The per-user Telegram conversation data stored by python-telegram-bot. User sessions track the active Spliit group in DMs, any pending command that should resume after group selection, and the active expense draft during `/add` intake.
