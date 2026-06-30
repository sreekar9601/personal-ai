---
when_to_use: Answering money questions and reviewing spending. Triggered by /finance and by finance questions in chat.
tier: default
---
# Finance playbook

The ledger is `finance/transactions/ledger.csv`, built by importing raw exports
the user drops in `finance/imports/`. You query it with the `finance_query` tool
(read-only SQL over a view named `ledger`). Columns:

`id, date (DATE), description, amount (DOUBLE, spend<0 / income>0), category, account, source`

## Answering a money question
1. Translate the question into one `finance_query` SELECT. Examples:
   - *"What did I spend on dining in May?"* →
     `SELECT ROUND(SUM(amount),2) FROM ledger WHERE category='dining' AND strftime(date,'%Y-%m')='2026-05'`
   - *"Biggest expenses last month?"* →
     `SELECT date, description, amount FROM ledger WHERE amount<0 AND strftime(date,'%Y-%m')='2026-05' ORDER BY amount ASC LIMIT 10`
   - *"Where does my money go?"* → group by category, order by SUM(amount).
2. Report the number plainly, with the period and any caveat (e.g. uncategorised
   spend). Spends are negative — say "$320 on dining", not "-320".
3. Only write to the vault if the user asked you to save a note or dashboard.

## Reviewing categories
- A large `uncategorized` total means the rules in `finance/categories.yaml` have
  a gap. Inspect the offending descriptions
  (`SELECT description, COUNT(*) FROM ledger WHERE category='uncategorized' GROUP BY 1 ORDER BY 2 DESC`),
  propose new keyword rules, and (with the user's ok, since it changes
  classification) update `finance/categories.yaml`. Re-categorisation takes
  effect on the next import; note that.

## Guardrails
- `finance_query` is read-only by design — never attempt INSERT/UPDATE/DELETE.
- Never invent numbers. If the ledger is empty, say so and tell the user to drop
  a CSV in `finance/imports/` and run `/import`.
- Money is sensitive: report figures, don't speculate about the user's habits
  unless asked.
