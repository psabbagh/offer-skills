# Offer Skills

**To set it up, open Claude Code and paste this message:**

```text
Install the Offer Skills plugin from https://github.com/psabbagh/offer-skills
```

Claude Code is the **Code** tab in the Claude desktop app, or the `claude` command in your
terminal. The regular Claude chat can't install plugins. Using Codex, or want to type the
commands yourself? See [Set it up](#1-set-it-up).

Three free skills for your offer. Type `/offer`, paste your website, and it finds what your
competitors offer and charge, shows where your price sits, then rebuilds your offer on the ideas
in Alex Hormozi's book *$100M Offers* and tests it against your old one on simulated buyers.
Works in **Claude Code** and **Codex**. No API keys, nothing to sign up for.

## 1. Set it up

**The easy way.** Open Claude Code and paste the message above. Claude runs the two install
commands below for you. When it's done, start a new session so the skills load.

**Or type the two commands yourself.** In your computer's terminal, one at a time:

```bash
claude plugin marketplace add psabbagh/offer-skills
```

```bash
claude plugin install offer-skills@offer-skills
```

**Codex.** In your terminal:

```bash
codex plugin marketplace add psabbagh/offer-skills
```

```bash
codex plugin add offer-skills@offer-skills
```

Start Codex with `codex --search`, so it can search the web.

## 2. Your first run

In a new session, type:

```text
/offer https://your-website.example
```

It reads your site, says back what you sell and to whom, and asks before it searches. Then it
finds your competitors, reads their pages and shows you the table. From there it offers the next
two steps: where your price sits, and the new offer.

## The three skills

| Skill | What it does |
|---|---|
| `offer` | Finds your competitors online (web search, the public Meta Ad Library, their sales and pricing pages) and near you, reads their pages, and builds one table of every service, package, price and guarantee. Every price is checked word for word against the page or ad it came from; a price nobody publishes stays **unknown**, never a guess. Keeps every run, and next time tells you what changed: prices raised, new competitors, guarantees dropped. |
| `offer-price` | Where your price sits, service by service, against the published prices: how many charge more and less, the middle of the market, and what each sale leaves you at each price. Ends with the moves the evidence supports, for you to approve. |
| `offer-build` | Scores your offer and your competitors' on seven questions, each score backed by a quote from what was read, rebuilds your offer, drafts the page and a short pitch, and refuses any price, number, guarantee, limit or deadline you did not approve. Then the same simulated buyers see your old offer and your new one, and it counts who would buy each. |

## What it needs

- Python 3.9 or newer. The Python that comes with macOS works.
- Web search: built into Claude Code; in Codex, start it with `codex --search`.
- For the Meta Ad Library (optional): a browser the agent can read, such as Claude in Chrome or
  the browser in the Claude desktop app. It is read-only and needs no account.

Everything it finds is kept in `~/offer-library` (change it with `OFFER_LIBRARY`).

## Works in

Tested on 2026-11-21.

| Host | What works |
|---|---|
| Claude Code | All three skills end to end, including the Meta Ad Library and the buyer test on 100 simulated buyers. A real run found 57 competitors from 11 searches and one Ad Library search, and checked 22 published prices word for word. |
| Codex CLI | All three skills except the Meta Ad Library (no browser). The buyer test was not run in Codex. Start it with `codex --search` and allow network access for reading pages. |
| Claude chat (claude.ai), ChatGPT | Not supported. |

## What it does not do

**It cannot see prices nobody publishes.** Many businesses quote on a call. Those stay unknown,
and the counts say how many.

**"Your competitors" means the ones the searches find.** A business with no website and no
search presence will be missed. It does not scrape Google Maps.

**It does not change anything.** It never publishes, edits your website, changes a price,
contacts anyone or signs in anywhere. Every output is a file for you.

**It does not promise for you.** The new offer only uses prices, guarantees, numbers, limits,
deadlines and extras you approve, and a check refuses anything else. It never invents scarcity.

**Simulated buyers are not customers.** They are good at showing objections and what would change
a mind, and bad at predicting real sales. Read the gap between old and new, not the numbers on
their own, and test the winner on real people. For a high-ticket offer whose first step is a
call, expect few "would buy today" answers either way.

**It is not Alex Hormozi.** The offer ideas come from his book *$100M Offers*, summed up in our
own words, with nothing quoted. This is an independent tool, not made, reviewed or endorsed by
Alex Hormozi or Acquisition.com. The book is worth buying.

## License

MIT.
