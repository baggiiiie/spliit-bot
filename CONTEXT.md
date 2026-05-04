# Context

## Glossary

### Expense draft
A partially-filled expense being assembled before it becomes a pending expense confirmation. It may be missing title, amount, payer, participants, split mode, or split values.

### Expense draft intake
The process that turns `/add` user input, callback selections, and LLM extraction results into progress on an expense draft. Expense draft intake decides what draft information was learned, what is still missing, and whether the user should be prompted, rejected, or shown a confirmation.
