#!/usr/bin/env python3
"""Score, rebuild and test an offer for the offer-build skill. Python 3.9+, standard library only,
no network.

    build.py facts [--run R | --business B]                     write facts.json to fill in, if missing
    build.py score [--run R | --business B]                     check scores.json against the evidence, rank everyone
    build.py check-copy FILE [--run R | --business B]           refuse any claim the owner did not approve
    build.py panel --customer customer.json --old old.md --new new.md [--n 100 | --quick] [--seed S]
    build.py compare [--run R | --business B]                   old offer vs new on the same buyers

Everything is read from and written to the offer skill's run folder in the library, so the
research, the price position and the new offer stay together.

The scorecard has seven questions, each 0 to 3. A score above 0 needs a short quote, and the
quote must be found word for word on a page or ad the research read for that business (for the
owner's new offer, in the draft or the approved facts). A score with no evidence becomes 0.

The buyer test runs buyers.py (an identical copy of the startup-buyers tool) twice with the same
seed and the same customer profile, so the same simulated buyers see the old offer and the new
one. The tool never answers for a buyer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from offerlib import OfferError, found_in, read_json, read_jsonl, resolve_run, write_json, write_text  # noqa: E402

QUESTIONS = [
    ("outcome", "Does it say plainly what result the buyer gets?"),
    ("proof", "Does it show that this works for people like the buyer (results, reviews, numbers)?"),
    ("speed", "Does it say how soon the first result comes?"),
    ("ease", "Does it say what the buyer no longer has to do or figure out alone?"),
    ("risk", "Does it take the risk off the buyer (a guarantee, a trial, pay on results)?"),
    ("stack", "Do the extras solve the problems the buyer meets next?"),
    ("now", "Is there an honest reason to act now?"),
]
MAX = 3 * len(QUESTIONS)
FACT_KINDS = ("prices", "guarantees", "numbers", "limits", "deadlines", "bonuses", "proof")

FACTS_TEMPLATE = {
    "business": "",
    "offer_name": "",
    "_read_me": ("Only what the owner approved goes in here. The copy check refuses any price, number, "
                 "guarantee, limit, deadline or bonus that is not written below, word for word."),
    "prices": [], "guarantees": [], "numbers": [], "limits": [], "deadlines": [], "bonuses": [], "proof": [],
}


def run_of(a) -> str:
    return resolve_run(getattr(a, "run", None), getattr(a, "business", None))


# ---------------------------------------------------------------- facts

def load_facts(run: str) -> dict:
    facts = read_json(os.path.join(run, "facts.json"))
    for k in FACT_KINDS:
        v = facts.get(k, [])
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise OfferError("facts.json: %s must be a list of approved lines (strings)" % k)
        facts[k] = [x.strip() for x in v if x.strip()]
    return facts


def cmd_facts(a):
    run = run_of(a)
    path = os.path.join(run, "facts.json")
    if os.path.exists(path):
        f = load_facts(run)
        print("facts.json already there: " + ", ".join("%d %s" % (len(f[k]), k) for k in FACT_KINDS))
        return 0
    t = dict(FACTS_TEMPLATE)
    info = read_json(os.path.join(run, "run.json"), default={})
    t["business"] = info.get("business", "")
    write_json(path, t)
    print("wrote %s: fill it only with what the owner approves" % path)
    return 0


# ---------------------------------------------------------------- score

def evidence_pool(run: str) -> dict:
    """key -> all text read for that business; 'you-new' -> the new offer draft plus approved facts."""
    pool = {}
    for p in read_jsonl(os.path.join(run, "pages.jsonl")) + read_jsonl(os.path.join(run, "agent-pages.jsonl")):
        pool[p.get("key", "")] = pool.get(p.get("key", ""), "") + "\n" + (p.get("text") or "")
    comps = read_json(os.path.join(run, "competitors.json"), default={"competitors": []})
    ads = {ad["library_id"]: ad for ad in read_json(os.path.join(run, "ads.json"), default=[])}
    for c in comps["competitors"]:
        for lib in c.get("ads", []):
            if lib in ads:
                pool[c["key"]] = pool.get(c["key"], "") + "\n" + ads[lib]["text"]
    new = ""
    for name in ("offer-new.md", "page.md", "pitch-new.md"):
        path = os.path.join(run, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                new += "\n" + fh.read()
    if os.path.exists(os.path.join(run, "facts.json")):
        f = load_facts(run)
        new += "\n" + "\n".join(x for k in FACT_KINDS for x in f[k])
    pool["you-new"] = new
    return pool


def check_scores(run: str):
    scores = read_json(os.path.join(run, "scores.json"))
    if not isinstance(scores, list):
        raise OfferError("scores.json must be a list, one entry per offer")
    pool = evidence_pool(run)
    names = {c["key"]: c["name"] for c in read_json(os.path.join(run, "competitors.json"))["competitors"]}
    names["you"] = "you (today)"
    names["you-new"] = "you (new offer)"
    out, notes = [], []
    for i, s in enumerate(scores, 1):
        key = s.get("competitor", "")
        if key not in names:
            raise OfferError("scores.json entry %d: %r is not a competitor key, 'you' or 'you-new'" % (i, key))
        text = pool.get(key, "")
        total, detail = 0, {}
        for q, _ in QUESTIONS:
            item = (s.get("ratings") or {}).get(q) or {}
            try:
                score = int(item.get("score", 0))
            except (TypeError, ValueError):
                raise OfferError("%s: %s score must be 0 to 3" % (key, q))
            if score < 0 or score > 3:
                raise OfferError("%s: %s score must be 0 to 3" % (key, q))
            quote = (item.get("quote") or "").strip()
            if score > 0 and not quote:
                notes.append("%s, %s: a score of %d with no quote became 0" % (names[key], q, score))
                score = 0
            elif score > 0 and not found_in(quote, text):
                notes.append("%s, %s: quote %r is not in what was read for them; score became 0" % (
                    names[key], q, quote[:80]))
                score = 0
            detail[q] = {"score": score, "quote": quote if score else "", "why": item.get("why", "")}
            total += score
        out.append({"competitor": key, "name": names[key], "package": s.get("package", ""), "total": total,
                    "ratings": detail})
    out.sort(key=lambda r: -r["total"])
    rank, last = 0, None
    for n, r in enumerate(out, 1):
        if r["total"] != last:
            rank, last = n, r["total"]
        r["rank"] = rank
    return out, notes


def cmd_score(a):
    run = run_of(a)
    ranked, notes = check_scores(run)
    write_json(os.path.join(run, "scorecard.json"), {"max": MAX, "questions": QUESTIONS, "ranked": ranked,
                                                     "notes": notes})
    lines = ["# Offer scorecard", "",
             "Seven questions, 0 to 3 each, %d in all. A score above 0 needs a quote found word for word in "
             "what was read. It is a judgment from the evidence, not a measurement of sales." % MAX, "",
             "| Rank | Offer | Score | " + " | ".join(q for q, _ in QUESTIONS) + " |",
             "|---|---|---|" + "---|" * len(QUESTIONS)]
    for r in ranked:
        lines.append("| %d | %s | %d/%d | %s |" % (r["rank"], r["name"] + (" (%s)" % r["package"] if r["package"] else ""),
                                                 r["total"], MAX, " | ".join(str(r["ratings"][q]["score"]) for q, _ in QUESTIONS)))
    if notes:
        lines += ["", "Scores set to 0 for lack of evidence:", ""] + ["- " + n for n in notes]
    write_text(os.path.join(run, "scorecard.md"), "\n".join(lines) + "\n")
    n = len(ranked)
    for who in ("you", "you-new"):
        mine = [r for r in ranked if r["competitor"] == who]
        if mine:
            print("%s: %d/%d, rank %d of %d" % (mine[0]["name"], mine[0]["total"], MAX, mine[0]["rank"], n))
    print("%d offers scored; %d scores set to 0 for lack of evidence; wrote scorecard.md" % (n, len(notes)))
    return 0


# ---------------------------------------------------------------- the copy check

MONEY = re.compile(r"(?:us\$|ca\$|a\$|\$|€|£)\s?\d[\d,.]*\s?k?\b|\b\d[\d,.]*\s?(?:usd|eur|gbp|dollars|euros|pounds)\b", re.I)
NUMBER = re.compile(r"(?<![\w$€£])\d[\d,.]*(?:\s?%|\s?x\b|\s?k\b)?")
NUMBER_WORDS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|"
                          r"thirty|forty|fifty|sixty|ninety|hundred|thousand|million|double|triple|half)\b", re.I)
GUARANTEE = re.compile(r"guarantee|money[- ]back|refund|risk[- ]free|no[- ]risk|or you don'?t pay|"
                       r"or (?:it'?s|its) free|pay nothing|or your money|we'?ll keep working", re.I)
LIMIT = re.compile(r"\bonly\b[^.!?\n]{0,30}\b(?:spots?|seats?|places?|clients?|left|available)|limited|"
                   r"spots? left|seats? left|capacity|waitlist|few (?:spots|places|seats)|exclusive|"
                   r"first \d+|max(?:imum)? of", re.I)
_DAYS = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|midnight|tonight|today|tomorrow|noon)"
DEADLINE = re.compile(r"deadline|expires?\b|expiring|today only|last chance|this week only|price goes up|"
                      r"while (?:it|they|stocks?) lasts?|hurry|"
                      r"\b(?:offer|sale|price|deal|discount|enrol\w*|registration|doors?|cart|spots?|applications?)\s+"
                      r"(?:ends?|closes?|expires?|goes up|rises?)|"
                      r"\b(?:ends?|ending|closes?|closing|until|by|before)\s+(?:on\s+|at\s+|this\s+|next\s+)?"
                      r"(?:%s|the end of|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|\d)" % _DAYS, re.I)
BONUS = re.compile(r"\bbonus(?:es)?\b|\bfree\b(?! (?:call|consultation)\b)|included at no|thrown in|gift", re.I)
ENDORSE = re.compile(r"hormozi|acquisition\.com|\$100m", re.I)


def _sentences(text: str) -> list:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        # list markers and heading signs are layout, not claims
        line = re.sub(r"^\s*(?:#+\s*|[-*\u2022]\s+|\d{1,2}[.)]\s+)", "", line)
        for s in re.split(r"(?<=[.!?])\s+", line):
            if s.strip():
                out.append((n, s.strip()))
    return out


def _without(sentence: str, approved: list) -> str:
    """The sentence with every approved fact in it taken out: only the rest needs checking."""
    rest = sentence
    for fact in sorted(approved, key=len, reverse=True):
        words = [re.escape(w) for w in fact.split()]
        if words:
            rest = re.sub(r"\s+".join(words), " ", rest, flags=re.I)
    return rest


def _numbers_in(text: str) -> set:
    return {re.sub(r"[\s,]", "", m.group(0)).lower().rstrip(".") for m in NUMBER.finditer(text)}


def check_copy(text: str, facts: dict, competitor_names: list) -> list:
    """Problems in a draft: each is (line, kind, sentence, why). An empty list means it passes."""
    approved_all = "\n".join(x for k in FACT_KINDS for x in facts[k])
    approved_numbers = _numbers_in(approved_all)
    problems = []

    approved = [x for k in FACT_KINDS for x in facts[k]]
    for line, s in _sentences(text):
        rest = _without(s, approved)
        stray = sorted(x for x in _numbers_in(rest) if x not in approved_numbers)
        if stray:
            problems.append((line, "number", s, "not in the approved facts: " + ", ".join(stray)))
        for m in MONEY.finditer(rest):
            amount = re.sub(r"[\s,]", "", m.group(0)).lower()
            if not any(amount in re.sub(r"[\s,]", "", f).lower() for f in facts["prices"]):
                problems.append((line, "price", s, "%s is not an approved price" % m.group(0).strip()))
        w = NUMBER_WORDS.search(rest)
        if w:
            problems.append((line, "number", s, "%r is a number in words that no approved fact uses" % w.group(0)))
        if GUARANTEE.search(rest):
            problems.append((line, "guarantee", s, "a guarantee must use an approved guarantee word for word"))
        if LIMIT.search(rest):
            problems.append((line, "limit", s, "a limit must use an approved limit word for word; never invent scarcity"))
        if DEADLINE.search(rest):
            problems.append((line, "deadline", s, "a deadline must use an approved deadline word for word"))
        if BONUS.search(rest):
            problems.append((line, "bonus", s, "an extra or 'free' item must be an approved bonus word for word"))
        if ENDORSE.search(s):
            problems.append((line, "endorsement", s, "the copy must not name Alex Hormozi, his book or company"))
        for name in competitor_names:
            if len(name) > 3 and re.search(r"\b%s\b" % re.escape(name), s, re.I):
                problems.append((line, "competitor", s, "names a competitor (%s)" % name))
    return problems


def cmd_check_copy(a):
    run = run_of(a)
    facts = load_facts(run)
    with open(a.file, encoding="utf-8") as fh:
        text = fh.read()
    comps = read_json(os.path.join(run, "competitors.json"), default={"competitors": []})["competitors"]
    names = [c["name"] for c in comps if c.get("name") and not c["name"].startswith("name:")]
    problems = check_copy(text, facts, names)
    if not problems:
        print("PASS: every price, number, guarantee, limit, deadline and extra in %s is approved" % a.file)
        return 0
    print("REFUSED: %d claims in %s are not in the approved facts" % (len(problems), a.file))
    for line, kind, s, why in problems:
        print("  line %d [%s] %s\n      %s" % (line, kind, s[:140], why))
    return 1


# ---------------------------------------------------------------- old offer vs new, on the same buyers

def buyers(args: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, os.path.join(HERE, "buyers.py")] + args,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)


def cmd_panel(a):
    run = run_of(a)
    customer = read_json(a.customer)
    n = 20 if a.quick else a.n
    seed = a.seed if a.seed is not None else 41
    made = {}
    for side, pitch, price in (("old", a.old, a.old_price), ("new", a.new, a.new_price)):
        d = os.path.join(run, "buyers", side)
        os.makedirs(d, exist_ok=True)
        c = dict(customer)
        if price is not None:
            c["offer_price"] = price
        cpath = os.path.join(d, "customer.json")
        write_json(cpath, c)
        p = buyers(["--dir", d, "init", "--customer", cpath, "--pitch", pitch, "--n", str(n), "--seed", str(seed),
                    "--replace"])
        if p.returncode != 0:
            raise OfferError("buyers.py init (%s): %s" % (side, p.stdout.strip()))
        made[side] = d
    cards_old = read_json(os.path.join(made["old"], "cards.json"), default=None)
    cards_new = read_json(os.path.join(made["new"], "cards.json"), default=None)
    if cards_old is not None and cards_new is not None:
        if cards_old != cards_new:
            raise OfferError("the two panels got different buyers; use the same customer profile")
    write_json(os.path.join(run, "buyers", "panel.json"), {"n": n, "seed": seed, "old": a.old, "new": a.new})
    print("two panels of the same %d buyers (seed %d):" % (n, seed))
    for side in ("old", "new"):
        print("  %s offer: %s" % (side, made[side]))
    print("next, for each folder: buyers.py --dir <folder> briefs, one sub-agent per brief, then build.py compare")
    return 0


def cmd_compare(a):
    run = run_of(a)
    res = {}
    for side in ("old", "new"):
        d = os.path.join(run, "buyers", side)
        p = buyers(["--dir", d, "tally"])
        if p.returncode != 0:
            raise OfferError("buyers.py tally (%s): %s" % (side, p.stdout.strip()))
        res[side] = read_json(os.path.join(d, "results.json"))
    sys.path.insert(0, HERE)
    import buyers as panel_tool  # the same checks buyers.py tally uses
    answers = {}
    for side in ("old", "new"):
        d = os.path.join(run, "buyers", side, "answers")
        answers[side] = {}
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".json") and panel_tool.problem(os.path.join(d, f), f[:-5]) is None:
                    answers[side][f[:-5]] = read_json(os.path.join(d, f))["decision"]
    both = sorted(set(answers["old"]) & set(answers["new"]))
    won = [b for b in both if answers["old"][b] != "buy_now" and answers["new"][b] == "buy_now"]
    lost = [b for b in both if answers["old"][b] == "buy_now" and answers["new"][b] != "buy_now"]
    o, nw = res["old"], res["new"]
    head = "%d of %d would buy today with the old offer, %d of %d with the new one." % (
        o["buy_now"], o["answered"], nw["buy_now"], nw["answered"])
    interest = "Interested (would buy today or probably later): %d with the old offer, %d with the new one." % (
        o["buy_now"] + o["counts"]["probably"], nw["buy_now"] + nw["counts"]["probably"])
    lines = ["# Old offer vs new, on the same simulated buyers", "", head, interest, "",
             "| | Old offer | New offer |", "|---|---|---|",
             "| Would buy today | %d | %d |" % (o["buy_now"], nw["buy_now"]),
             "| Probably, later | %d | %d |" % (o["counts"]["probably"], nw["counts"]["probably"]),
             "| Not now | %d | %d |" % (o["counts"]["not_now"], nw["counts"]["not_now"]),
             "| No | %d | %d |" % (o["counts"]["no"], nw["counts"]["no"]), "",
             "Buyer by buyer (the same %d people saw both): %d moved to buying, %d stopped buying." % (
                 len(both), len(won), len(lost)), "",
             "These are simulated buyers, each a separate AI sub-agent playing one person from your customer "
             "profile. It is a cheap first test of the offer's pull, not a forecast of sales. The two panels "
             "answered separately, so part of any small difference is chance. Test the winner on real people."]
    write_text(os.path.join(run, "buyers", "compare.md"), "\n".join(lines) + "\n")
    write_json(os.path.join(run, "buyers", "compare.json"), {
        "old_buy_now": o["buy_now"], "old_answered": o["answered"], "new_buy_now": nw["buy_now"],
        "new_answered": nw["answered"], "moved_to_buy": won, "stopped_buying": lost, "paired": len(both)})
    print(head)
    print(interest)
    print("same buyers: %d moved to buying, %d stopped; wrote %s" % (
        len(won), len(lost), os.path.join(run, "buyers", "compare.md")))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn):
        sp = sub.add_parser(name)
        sp.add_argument("--run")
        sp.add_argument("--business")
        sp.set_defaults(fn=fn)
        return sp

    add("facts", cmd_facts)
    add("score", cmd_score)
    add("check-copy", cmd_check_copy).add_argument("file")
    pn = add("panel", cmd_panel)
    pn.add_argument("--customer", required=True)
    pn.add_argument("--old", required=True)
    pn.add_argument("--new", required=True)
    pn.add_argument("--old-price", type=float)
    pn.add_argument("--new-price", type=float)
    pn.add_argument("--n", type=int, default=100)
    pn.add_argument("--quick", action="store_true")
    pn.add_argument("--seed", type=int)
    add("compare", cmd_compare)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except OfferError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
