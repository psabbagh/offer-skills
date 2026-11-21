#!/usr/bin/env python3
"""Where a business's price sits against its competitors' published prices. Python 3.9+,
standard library only, no network.

    price.py position [--run R | --business B]          service by service, from the checked table
    price.py margin --numbers numbers.json [--price P ...] [--run R | --business B]
    price.py moves [--numbers numbers.json] [--run R | --business B]
    price.py approve 1,3 [--run R | --business B]       record the moves the owner said yes to

It reads table.json, which the offer skill's `offer.py table` writes after checking every price
word for word. Only checked prices count. Unknown prices are counted and shown, never filled in,
and prices are compared only with prices of the same service, currency and period (a monthly
price is never set against a one-off price).

`margin` runs numbers.py (an identical copy of the startup-numbers tool) at each price, so a move
is shown with what one sale leaves after its own costs and the break-even.
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
from offerlib import OfferError, median, money, quantile, read_json, resolve_run, write_json, write_text  # noqa: E402

MIN_EVIDENCE = 3  # fewer published prices than this is too little to call a position


def groups(table: dict) -> list:
    """One group per (service, currency, period) that the owner sells or competitors price."""
    rows = table["rows"]
    out = {}
    for r in rows:
        if r["service"] == "(nothing found)":
            continue
        k = (r["service"], r.get("currency") or "", r.get("period") or "")
        out.setdefault(k, {"service": r["service"], "currency": r.get("currency"), "period": r.get("period"),
                           "known": [], "you": [], "unknown": set()})
        g = out[k]
        if r["competitor"] == "you":
            if r["amount"] is not None:
                g["you"].append(r)
            continue
        if r["status"] == "checked" and r["amount"] is not None:
            g["known"].append(r)
    # competitors that sell the service but publish no comparable price, per service
    by_service = {}
    for r in rows:
        if r["competitor"] != "you" and r["service"] != "(nothing found)":
            by_service.setdefault(r["service"], set()).add(r["competitor"])
    for g in out.values():
        priced = {r["competitor"] for r in g["known"]}
        g["unknown"] = sorted(by_service.get(g["service"], set()) - priced)
    return sorted(out.values(), key=lambda g: (-len(g["you"]), -len(g["known"]), g["service"]))


def position_of(g: dict) -> dict:
    amounts = sorted(r["amount"] for r in g["known"])
    res = {"service": g["service"], "currency": g["currency"], "period": g["period"], "n": len(amounts),
           "unknown": len(g["unknown"]), "min": amounts[0] if amounts else None,
           "q1": quantile(amounts, 0.25), "median": median(amounts), "q3": quantile(amounts, 0.75),
           "max": amounts[-1] if amounts else None, "you": None, "cheaper_than": None, "dearer_than": None,
           "same": None, "band": "no price of yours", "rows": [
               {"name": r["name"], "package": r["package"], "price_text": r["price_text"], "amount": r["amount"],
                "source_url": r["source_url"]} for r in sorted(g["known"], key=lambda r: r["amount"])]}
    if g["you"]:
        mine = min(r["amount"] for r in g["you"])
        res["you"] = mine
        res["you_text"] = ", ".join(r["price_text"] for r in g["you"])
        res["cheaper_than"] = sum(1 for x in amounts if x > mine)
        res["dearer_than"] = sum(1 for x in amounts if x < mine)
        res["same"] = sum(1 for x in amounts if x == mine)
        if len(amounts) < MIN_EVIDENCE:
            res["band"] = "too little evidence"
        elif mine < res["q1"]:
            res["band"] = "bottom quarter"
        elif mine > res["q3"]:
            res["band"] = "top quarter"
        else:
            res["band"] = "middle half"
    return res


def run_numbers(numbers_path: str, price: float | None) -> dict:
    cmd = [sys.executable, os.path.join(HERE, "numbers.py"), numbers_path, "--json"]
    if price is not None:
        cmd += ["--price", repr(float(price))]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if p.returncode != 0:
        raise OfferError("numbers.py could not read %s: %s" % (numbers_path, (p.stderr or p.stdout).strip()[:300]))
    return json.loads(p.stdout)


def margin_line(d: dict) -> dict:
    per = d.get("contribution")
    cost = (d.get("variable") or 0) + (d.get("marketing_per_sale") or d.get("cost_to_win_customer") or 0) \
        if d.get("model") == "one-time" else (d.get("variable") or 0)
    return {"price": d["price"], "leaves_per_sale": per, "margin": d.get("margin"), "breakeven": d.get("breakeven"),
            "floor": cost, "year1_profit": d.get("year1_profit"), "unit": d.get("unit")}


def load(a):
    run = resolve_run(a.run, a.business)
    path = os.path.join(run, "table.json")
    if not os.path.exists(path):
        raise OfferError("no table.json in %s yet: run offer.py table first" % run)
    return run, read_json(path)


def describe(p: dict) -> str:
    cur = p["currency"]
    per = (" a " + p["period"]) if p["period"] and p["period"] != "one-time" else ""
    head = "**%s**%s" % (p["service"], " (%s)" % p["period"] if p["period"] else "")
    if p["n"] == 0:
        return "%s: no competitor publishes a comparable price (%d sell it with the price unknown)." % (head, p["unknown"])
    if p["n"] == 1:
        spread = "1 published price, %s%s" % (money(p["min"], cur), per)
    else:
        spread = "%d published prices from %s to %s, middle %s%s" % (
            p["n"], money(p["min"], cur), money(p["max"], cur), money(p["median"], cur), per)
    if p["you"] is None:
        return "%s: %s. You have no price for it in the table." % (head, spread)
    you = "you charge %s%s: cheaper than %d, dearer than %d, the same as %d" % (
        money(p["you"], cur), per, p["cheaper_than"], p["dearer_than"], p["same"])
    band = {"bottom quarter": "That is in the cheapest quarter.", "top quarter": "That is in the dearest quarter.",
            "middle half": "That is in the middle half.",
            "too little evidence": "Fewer than %d published prices, so this is not a position yet." % MIN_EVIDENCE}[p["band"]]
    return "%s: %s; %s. %s %d more sell it with no comparable published price." % (head, spread, you, band, p["unknown"])


def cmd_position(a):
    run, table = load(a)
    pos = [position_of(g) for g in groups(table)]
    write_json(os.path.join(run, "position.json"), pos)
    lines = ["# Where your price sits: %s" % table["business"], "",
             "Only prices checked word for word against their source count. Unknown prices are counted, never "
             "guessed, and are not cheap or expensive. Prices are compared only within the same service, currency "
             "and period.", ""]
    for p in pos:
        lines.append("- " + describe(p))
    write_text(os.path.join(run, "position.md"), "\n".join(lines) + "\n")
    for p in pos:
        print(describe(p).replace("**", ""))
    print("wrote %s" % os.path.join(run, "position.md"))
    return 0


def cmd_margin(a):
    rows = [margin_line(run_numbers(a.numbers, None))]
    for p in a.price or []:
        rows.append(margin_line(run_numbers(a.numbers, p)))
    for r in rows:
        print("at %s a %s: each sale leaves %s after its own costs; break-even %s a month; floor %s" % (
            money(r["price"]), r["unit"] or "sale", money(r["leaves_per_sale"]),
            "never" if r["breakeven"] is None else "%.0f sales" % r["breakeven"], money(r["floor"])))
    return 0


def nice(v):
    """A suggested price a person would charge: whole dollars, then steps of 5 and 50."""
    if v is None:
        return None
    step = 50 if v >= 1000 else 5 if v >= 100 else 1
    return float(int(v / step + 0.5) * step)


def suggest(p: dict, floor: float | None) -> list:
    """Moves the evidence supports. Each names its evidence; none is applied by itself."""
    cur, out = p["currency"], []
    if p["you"] is None or p["band"] == "no price of yours":
        return out
    per = (" a " + p["period"]) if p["period"] and p["period"] != "one-time" else ""
    if p["band"] == "too little evidence":
        out.append(("hold %s at %s%s" % (p["service"], money(p["you"], cur), per),
                    "only %d competitors publish a comparable price, too few to move on" % p["n"]))
        return out
    if p["band"] == "bottom quarter":
        out.append(("raise %s to %s%s, the middle of the market" % (p["service"], money(nice(p["median"]), cur), per),
                    "%d of %d published prices are above yours" % (p["cheaper_than"], p["n"])))
        out.append(("raise %s to %s%s, the edge of the cheapest quarter" % (p["service"], money(nice(p["q1"]), cur), per),
                    "a smaller step that keeps you among the cheaper offers"))
    elif p["band"] == "top quarter":
        out.append(("hold %s at %s%s and make the offer carry it (guarantee, extras, proof)" % (
            p["service"], money(p["you"], cur), per),
                    "you are dearer than %d of %d published prices; the offer has to show why" % (p["dearer_than"], p["n"])))
        out.append(("add a smaller package of %s near %s%s" % (p["service"], money(nice(p["median"]), cur), per),
                    "the middle of %d published prices" % p["n"]))
    else:
        out.append(("hold %s at %s%s" % (p["service"], money(p["you"], cur), per),
                    "you sit in the middle half of %d published prices" % p["n"]))
        if p["q3"] and p["q3"] > p["you"]:
            out.append(("raise %s to %s%s once the offer is stronger" % (p["service"], money(nice(p["q3"]), cur), per),
                        "the edge of the dearest quarter of %d published prices" % p["n"]))
    if floor is not None:
        kept = []
        for move, why in out:
            target = _target(move)
            if target is not None and target <= floor:
                why += "; below your cost of %s a sale, so it loses money" % money(floor, cur)
            kept.append((move, why))
        out = kept
    return out


def _target(move: str):
    m = re.search(r"to [^\d]*([\d,]+(?:\.\d+)?)", move) or re.search(r"near [^\d]*([\d,]+(?:\.\d+)?)", move)
    return float(m.group(1).replace(",", "")) if m else None


def cmd_moves(a):
    run, table = load(a)
    floor = None
    if a.numbers:
        floor = margin_line(run_numbers(a.numbers, None))["floor"]
    moves = []
    for g in groups(table):
        p = position_of(g)
        for move, why in suggest(p, floor):
            entry = {"n": len(moves) + 1, "service": p["service"], "move": move, "evidence": why, "approved": False,
                     "currency": p["currency"]}
            t = _target(move)
            if a.numbers and t:
                entry["at_that_price"] = margin_line(run_numbers(a.numbers, t))
            moves.append(entry)
    write_json(os.path.join(run, "moves.json"), moves)
    lines = ["# Price moves for %s to approve" % table["business"], "",
             "Each move names its evidence. Nothing changes until you say which ones you want.", ""]
    for m in moves:
        extra = ""
        if m.get("at_that_price"):
            r = m["at_that_price"]
            extra = " At that price each %s leaves %s%s after its own costs." % (
                r["unit"] or "sale", money(r["leaves_per_sale"], m.get("currency")),
                " a month" if (m.get("currency") and "a month" in m["move"]) else "")
        lines.append("%d. [ ] %s. Why: %s.%s" % (m["n"], m["move"], m["evidence"], extra))
    write_text(os.path.join(run, "moves.md"), "\n".join(lines) + "\n")
    print("\n".join(lines[4:]) if moves else "no moves: the table has no price of yours to place")
    return 0


def cmd_approve(a):
    run, table = load(a)
    path = os.path.join(run, "moves.json")
    moves = read_json(path)
    pick = {int(x) for x in a.numbers_list.split(",") if x.strip()}
    for m in moves:
        m["approved"] = m["n"] in pick
    write_json(path, moves)
    chosen = [m["move"] for m in moves if m["approved"]]
    print("approved: %s" % ("; ".join(chosen) if chosen else "none"))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("position", cmd_position), ("moves", cmd_moves), ("margin", cmd_margin), ("approve", cmd_approve)):
        sp = sub.add_parser(name)
        sp.add_argument("--run")
        sp.add_argument("--business")
        sp.set_defaults(fn=fn)
        if name in ("moves",):
            sp.add_argument("--numbers")
        if name == "margin":
            sp.add_argument("--numbers", required=True)
            sp.add_argument("--price", type=float, action="append")
        if name == "approve":
            sp.add_argument("numbers_list")
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except OfferError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
