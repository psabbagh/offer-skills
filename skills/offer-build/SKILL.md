---
name: offer-build
description: >-
  Rebuild a business's offer on the offer ideas in the book $100M Offers by Alex Hormozi (an
  independent tool, not made or endorsed by him or Acquisition.com), score it and every
  competitor's offer on the same seven questions with evidence quoted for each score, rank the
  owner against all of them, draft the offer page and a one-line pitch checked against facts the
  owner approved, then test the old offer and the new one on the same 100 simulated buyers ("31 of
  100 would buy today, 58 with the new offer"). Everything is a draft for approval. Use after /offer
  and offer-price, or when someone asks make my offer better, make an offer people can't refuse,
  write my offer page, give me a one-line pitch, how does my offer stack up, or would more people
  buy this, even if they do not say "offer".
argument-hint: "[business name] [--quick]"
---

# offer-build

Turn the research into a better offer, prove it is better on evidence, and test it on simulated
buyers before the owner spends a cent on it. Every promise in the new offer comes from the owner.
Nothing is published or sent.

What the user typed after the command: `$ARGUMENTS`. `--quick` means 20 buyers per panel instead of
100.

## The tool

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/build.py" <command> --business "<business name>"
```

Below, `TOOL` means exactly that, and `BUYERS` means
`python3 "${CLAUDE_SKILL_DIR}/scripts/buyers.py"` (the same tool as the startup-buyers skill). If
`${CLAUDE_SKILL_DIR}` is not expanded, use this skill's base directory. Python 3.9 or newer,
standard library only. Everything is read from and written to the newest run of the business in
the offer library (`~/offer-library`, or `$OFFER_LIBRARY`); `--run <folder>` picks another.

The ideas are in `references/offer-ideas.md`: read it before Step 3. Credit the book as the source
of the ideas whenever you explain them, say plainly that this tool is not endorsed by Alex Hormozi,
and never quote the book.

## Step 1: get the facts from the owner

```bash
TOOL facts --business "<business name>"
```

It writes `facts.json` in the run folder. Ask the owner, one short group at a time, and write only
what they confirm, in their words:

- `prices`: the price of the new offer, from the moves they approved in offer-price (`moves.json`),
  or the current price
- `guarantees`: any guarantee they will honour, exactly as they would state it
- `numbers`: results and counts they can prove ("42 agencies coached since 2023")
- `limits` and `deadlines`: only real ones ("We take 5 new agencies a month")
- `bonuses`: extras they will really include
- `proof`: testimonials or case studies they have permission to use

Suggest what the research shows competitors offer (a guarantee most of them give, an extra nobody
gives), but the owner decides. A blank list is fine. Never fill one in for them.

## Step 2: score every offer, theirs and the owner's

Score the owner's current offer (`you`) and each competitor with a published offer on the seven
questions in `scripts/build.py` (outcome, proof, speed, ease, risk, stack, now), 0 to 3 each. Write
`scores.json`:

```json
[{"competitor": "brightpath.example", "package": "Group", "ratings": {
   "outcome": {"score": 3, "quote": "Land three retainer clients in 90 days", "why": "a specific result"},
   "risk": {"score": 2, "quote": "30-day money-back guarantee", "why": "refund, but short"}}}]
```

A score above 0 needs a short `quote` copied word for word from that business's pages or ads in the
run (from `evidence.md` or `pages.jsonl`). With more than 15 competitors, score them in waves of 10
sub-agents, each given the questions and one competitor's evidence. Then:

```bash
TOOL score --business "<business name>"
```

Any score whose quote is not found in what was read becomes 0, and the tool says which. It ranks
everyone and writes `scorecard.md`. Tell the owner where they rank, on which questions they lose
points, and which competitors score highest and why.

## Step 3: rebuild the offer

With the owner, walk `references/offer-ideas.md` sections 2 to 5:

1. List the buyer's problems in order, from the research (what competitors promise, what their
   offers leave out) and from the owner.
2. Turn each into a part of the offer; keep what solves a real problem, cut filler.
3. Name it after the result, for the buyer it is for.
4. Add the risk reversal, extras, limits and deadlines, only from `facts.json`.
5. Price it from the approved moves.

Write three files in the run folder:

- `offer-new.md`: the offer, part by part, with what each part solves
- `page.md`: offer page copy for the owner's site
- `pitch-new.md`: three to six plain lines a buyer would see (what it is, for whom, the result, the
  risk reversal, the price, the first step). This is what the simulated buyers read.

Also write `pitch-old.md`: the current offer as it stands on their site, in the same plain shape,
with only facts from their own pages. No superlatives in either pitch; the test must be fair.

## Step 4: the copy check

```bash
TOOL check-copy <run folder>/page.md --business "<business name>"
TOOL check-copy <run folder>/pitch-new.md --business "<business name>"
TOOL check-copy <run folder>/offer-new.md --business "<business name>"
```

It refuses every price, number, guarantee, limit, deadline, extra or "free" item that is not in
`facts.json` word for word, any competitor's name, and any mention of Alex Hormozi, his book or his
company. Fix the copy (or ask the owner to approve the fact) until each says PASS. Never edit
`facts.json` to make a check pass without the owner's yes.

Then score the new offer as `you-new` in `scores.json` (quotes come from the new files and the
facts) and run `TOOL score` again: "You ranked 14th of 31; the new offer ranks 2nd."

## Step 5: test old vs new on the same buyers

Write the buyer profile, `customer.json` in the run folder, in the shape of `customer.example.json`
beside this file: who buys, two to four segments with income and budget ranges, how they shop,
what they use today (the competitors and the do-it-yourself way from the research), and what the
problem costs them. Show it to the owner in a few lines and let them correct it: a wrong customer
makes the whole test wrong. Then:

```bash
TOOL panel --business "<business name>" --customer <run>/customer.json --old <run>/pitch-old.md --new <run>/pitch-new.md --old-price <today's price> --new-price <new price> [--quick]
```

It deals the same buyers into two panels, `buyers/old` and `buyers/new`. Before running, tell the
owner it means 200 sub-agent runs (40 with `--quick`), a large share of their plan's usage, and
offer `--quick` first. For each panel:

```bash
BUYERS --dir <run>/buyers/old briefs
```

For each wave it lists, send ONE message with one sub-agent call per buyer: in Claude Code, the
Agent tool with `subagent_type` `general-purpose`, `description` `buyer <id>`, and `prompt`
`Read <brief path> and do exactly what it says. It is your whole brief.` Wait for the wave to end
before the next. Codex and other hosts: `references/hosts.md`. Then `BUYERS --dir <folder> check`,
rerun `briefs` once for any missing, and do the same for `buyers/new`. Never write or fix an answer
for a buyer. Then:

```bash
TOOL compare --business "<business name>"
```

`buyers/compare.md` gives the headline ("31 of 100 would buy today with the old offer, 58 with the
new one"), the full counts, and how many of the same buyers moved to buying or away. Tell the owner
the headline, the top reasons people still pass (from `buyers/new/results.md`), and what would
change their minds.

For a high-ticket offer whose first step is a call, "would buy today" stays near zero for any
pitch (in the first full test, a $3,000-a-month advisory went from 0 to 1 of 100, while many
buyers said they would book the call). There, lead with the interested line and the reasons, and
say why.

Say once, plainly: these are simulated buyers, good at surfacing objections and bad at predicting
real sales; language models lean agreeable, so read both numbers as best cases and the gap between
them as the useful part. The two panels answer separately, so a small gap may be chance. The next
step is to test the winner on real people.

## Step 6: hand it over

List the files: `offer-new.md`, `page.md`, `pitch-new.md`, `scorecard.md`, `buyers/compare.md`. All
are drafts for the owner to read and use themselves. Nothing was published, sent or changed.

## Rules

- Only facts the owner approved go into the offer. Never invent a result, a client, a number, a
  guarantee, scarcity or a deadline. The copy check enforces this in code; do not work around it.
- Never name a competitor in the owner's copy, and never copy a competitor's words into it.
- The scorecard is a judgment from quoted evidence, not a measurement of sales. Say so.
- Simulated buyers' words are research, never testimonials.
