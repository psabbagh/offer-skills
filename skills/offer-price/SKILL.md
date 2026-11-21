---
name: offer-price
description: >-
  Show where a business's price sits against its competitors' published prices, service by
  service: how many charge more and less, the middle of the market and the spread, with unknown
  prices counted and never filled in. Adds what each sale leaves after its own costs at the
  current price and at each suggested price, then lists the price moves the evidence supports for
  the owner to approve. Uses the checked table from the offer skill. Use after /offer, or when
  someone asks am I too cheap, am I charging enough, where does my price sit, what should I
  charge, should I raise my prices, even if they do not say "price".
argument-hint: "[business name]"
---

# offer-price

Where does the owner's price sit, and what move does the evidence support? This step answers
with numbers the owner can check, from prices that were checked word for word. It never changes a
price: it ends with a list for the owner to approve.

## The tool

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/price.py" <command> --business "<business name>"
```

Below, `TOOL` means exactly that. If `${CLAUDE_SKILL_DIR}` is not expanded, use this skill's base
directory. Python 3.9 or newer, standard library only. It reads the newest run of that business in
the offer library (`~/offer-library`, or `$OFFER_LIBRARY`); `--run <folder>` picks another run.

## Step 1: the table and their own prices

`table.json` must exist: if not, run `/offer` first. The owner's prices must be in it as rows with
`competitor` `you`. If they are missing, ask for each service's price and what it includes, add
them to the run's `offers.json` with `basis` `owner said`, and run the offer skill's `offer.py table`
again.

## Step 2: where it sits

```bash
TOOL position --business "<business name>"
```

For each service it compares only prices of the same service, currency and period (a monthly
price is never set against a one-off fee), and says: how many published prices, the lowest, the
middle and the highest, how many are above and below the owner's, which quarter the owner's price
is in, and how many competitors sell the service with no published price. With fewer than three
published prices it says there is too little evidence to call a position.

## Step 3: what each sale leaves (optional, recommended)

Ask whether they know their costs: what one sale or one customer costs them to deliver, and what
they spend to win one. If they do, write `numbers.json` in the run folder in the shape of
`numbers.example.json` beside this file (a subscription; for one-off sales see the comments at the
top of `scripts/numbers.py`), then:

```bash
TOOL margin --numbers <run folder>/numbers.json --price 450 --price 700
```

It runs `scripts/numbers.py` (the same tool as the startup-numbers skill) at the current price and
each price given, and says what each sale leaves after its own costs and the break-even. Mark every
number the owner did not give you as an estimate.

## Step 4: the moves, for approval

```bash
TOOL moves --business "<business name>" [--numbers <run folder>/numbers.json]
```

`moves.md` lists the moves the evidence supports, each with its evidence: raise toward the middle
when the price is in the cheapest quarter; hold and make the offer carry a price in the dearest
quarter, or add a smaller package; hold in the middle. With costs, a move that falls below the cost
of a sale is marked as losing money.

Tell the owner the position in two or three sentences, then show the list and ask which they want.
Record the answer:

```bash
TOOL approve 1,3 --business "<business name>"
```

Approved moves become facts `offer-build` may use. Then: "Want me to rebuild the offer around it
and test it on 100 simulated buyers? That's offer-build."

## Rules

- Only prices checked word for word count. Unknown prices are counted and shown, never guessed,
  averaged in or called cheap or expensive.
- A position is a fact about published prices, not a verdict on value. Say so when the owner's
  offer includes more or less than the others.
- Never change a price, a page or anything else. The owner decides.
