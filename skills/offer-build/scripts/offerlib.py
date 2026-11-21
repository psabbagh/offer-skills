"""Shared helpers for the offer, offer-price and offer-build skills.

Python 3.9+, standard library only, no network. This file is an identical copy in each of the
three skills; a test in each fails when the copies drift apart.

The library: every business gets a folder under the library root, and every research run a dated
folder inside it, so a later run can be compared with an earlier one.

    $OFFER_LIBRARY (default ~/offer-library)
      <business-slug>/
        2026-11-21/          one run: found.json, competitors.json, pages.jsonl, offers.json, table.json ...
        2026-12-05/
"""

from __future__ import annotations

import datetime
import json
import os
import re
import unicodedata

LIBRARY_ENV = "OFFER_LIBRARY"
RUN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-\d+)?$")


class OfferError(Exception):
    pass


# ---------------------------------------------------------------- library and runs

def library_root() -> str:
    root = os.environ.get(LIBRARY_ENV) or os.path.join(os.path.expanduser("~"), "offer-library")
    return os.path.abspath(os.path.expanduser(root))


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not slug:
        raise OfferError("cannot make a folder name from %r" % text)
    return slug[:60]


def business_dir(business: str) -> str:
    return os.path.join(library_root(), slugify(business))


def runs(business: str) -> list:
    """The run folders of a business, oldest first."""
    d = business_dir(business)
    if not os.path.isdir(d):
        return []
    names = [n for n in os.listdir(d) if RUN_RE.match(n) and os.path.isdir(os.path.join(d, n))]
    return [os.path.join(d, n) for n in sorted(names, key=_run_key)]


def _run_key(name: str):
    return (name[:10], int(name[11:]) if len(name) > 10 else 0)


def new_run(business: str, today: str | None = None) -> str:
    """A fresh dated run folder. A second run on the same day gets -2, -3 ..."""
    today = today or datetime.date.today().isoformat()
    base = business_dir(business)
    os.makedirs(base, exist_ok=True)
    name, i = today, 1
    while os.path.exists(os.path.join(base, name)):
        i += 1
        name = "%s-%d" % (today, i)
    path = os.path.join(base, name)
    os.makedirs(path)
    return path


def resolve_run(run: str | None, business: str | None) -> str:
    """--run wins; otherwise the newest run of --business."""
    if run:
        path = os.path.abspath(os.path.expanduser(run))
        if not os.path.isdir(path):
            raise OfferError("no such run folder: %s" % path)
        return path
    if business:
        found = runs(business)
        if not found:
            raise OfferError("no runs yet for %r in %s (start one with: offer.py start)" % (business, library_root()))
        return found[-1]
    raise OfferError("say which run: --run <folder> or --business <name>")


# ---------------------------------------------------------------- files

def read_json(path: str, default=None):
    if not os.path.exists(path):
        if default is not None:
            return default
        raise OfferError("missing file: %s" % path)
    with open(path, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except ValueError as e:
            raise OfferError("%s is not valid JSON: %s" % (path, e))


def write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def read_jsonl(path: str) -> list:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise OfferError("%s line %d is not valid JSON: %s" % (path, n, e))
    return out


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------- word-for-word matching

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {ord("‘"): "'", ord("’"): "'", ord("“"): '"', ord("”"): '"', ord(" "): " "}


def squash(text: str) -> str:
    """Text reduced for a word-for-word check: same characters, ignoring case, spacing,
    and the curly-quote or dash variant a page happened to use."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(_DASHES).translate(_QUOTES).lower()
    return re.sub(r"\s+", "", text)


def found_in(needle: str, haystack: str) -> bool:
    n = squash(needle)
    return bool(n) and n in squash(haystack)


# ---------------------------------------------------------------- prices

CURRENCY = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP",
            "ca$": "CAD", "cad": "CAD", "a$": "AUD", "aud": "AUD", "chf": "CHF"}
_AMOUNT = re.compile(
    r"(?P<cur>us\$|ca\$|a\$|\$|€|£|usd|eur|gbp|cad|aud|chf)?\s?"
    r"(?P<num>\d{1,3}(?:[,.\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s?(?P<k>k\b)?\s?"
    r"(?P<cur2>usd|eur|gbp|cad|aud|chf|€)?",
    re.I)
_PERIODS = [
    ("month", r"/\s?mo\b|/\s?month|per\s+month|a\s+month|monthly|\bmo\b|/m\b|p/m|pcm"),
    ("year", r"/\s?yr\b|/\s?year|per\s+year|a\s+year|yearly|annual|annually|/y\b|p\.a\."),
    ("week", r"/\s?wk\b|/\s?week|per\s+week|a\s+week|weekly"),
    ("hour", r"/\s?hr\b|/\s?hour|per\s+hour|an\s+hour|hourly"),
    ("session", r"per\s+session|/\s?session|a\s+session"),
]


def parse_amount(price_text: str):
    """The first money amount in a price as written: (amount, currency) or (None, None).
    "$1,500" -> (1500.0, 'USD'); "from 2.5k EUR" -> (2500.0, 'EUR'). No currency stays None."""
    for m in _AMOUNT.finditer(price_text or ""):
        cur = (m.group("cur") or m.group("cur2") or "").lower()
        raw = m.group("num").replace(" ", "")
        if re.search(r"[,.]\d{3}(?:[,.]|$)", raw):
            # thousands separators: 1,500 / 1.500 / 1,500.00 / 1.500,00
            cents = ""
            tail = re.search(r"[,.](\d{1,2})$", raw)
            if tail and not re.search(r"[,.]\d{3}$", raw):
                cents = tail.group(1)
                raw = raw[: tail.start()]
            raw = re.sub(r"[,.]", "", raw) + ("." + cents if cents else "")
        else:
            raw = raw.replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        if m.group("k"):
            value *= 1000
        return value, CURRENCY.get(cur)
    return None, None


def parse_period(*texts: str) -> str:
    joined = " ".join(t for t in texts if t).lower()
    # the period written first wins: "$970 / year (2 mo free)" is a yearly price
    hits = []
    for name, pattern in _PERIODS:
        m = re.search(pattern, joined)
        if m:
            hits.append((m.start(), name))
    if hits:
        return min(hits)[1]
    if re.search(r"one[- ]time|once|lifetime|single payment|pay in full|flat fee|per project|per visit", joined):
        return "one-time"
    return "one-time" if joined.strip() else ""


def money(value, currency=None) -> str:
    if value is None:
        return "unknown"
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$", "AUD": "A$"}.get(currency or "", "")
    if value == 0:
        return "free"
    text = "{:,.2f}".format(value).rstrip("0").rstrip(".") if value % 1 else "{:,.0f}".format(value)
    return sym + text if sym else (text + (" " + currency if currency else ""))


# ---------------------------------------------------------------- offer terms

# The fields of an offer row that hold words copied from a page, besides the price. Each is a list
# of short texts, and `offer.py table` checks every one word for word against the business's pages.
TERM_FIELDS = ("free_way_in", "commitment", "limits", "speed")
COPIED_LISTS = ("includes", "bonuses") + TERM_FIELDS

# How the table counts what competitors state. A tag only sorts words already checked on the page;
# it never adds a claim. (field, tag, what "N of M ..." says, pattern)
TERMS = [
    ("free_way_in", "free plan", "have a free plan",
     r"free\s+(?:plan|tier|forever|version|account|edition|package)|forever\s+free|free\s+to\s+start|freemium|\$0\b"),
    ("free_way_in", "free trial", "offer a free trial", r"\btrial\b"),
    ("free_way_in", "demo", "offer a demo", r"\bdemo\b"),
    ("free_way_in", "free quote", "give a free quote, inspection or consultation",
     r"quote|estimate|inspection|assessment|consult|audit|discovery\s+call|strategy\s+call"),
    ("commitment", "cancel anytime", "say cancel anytime",
     r"cancel\s+(?:at\s+)?any\s?time|no\s+(?:long[- ]term\s+)?contracts?\b|no\s+commitment|month[- ]to[- ]month|"
     r"no\s+lock[- ]?in"),
    ("commitment", "annual billing", "bill yearly", r"annual|yearly|per\s+year|/\s?y(?:ea)?r\b"),
    ("commitment", "setup fee", "charge a setup fee",
     r"set[- ]?up\s+(?:fee|cost|charge)|onboarding\s+fee|implementation\s+fee|activation\s+fee"),
    ("commitment", "minimum contract", "ask for a minimum contract",
     r"\d+[- ](?:month|year)s?\s+(?:contract|minimum|commitment|term)|minimum\s+(?:term|contract|commitment)"),
    ("commitment", "deposit", "take a deposit", r"deposit"),
    ("commitment", "call-out fee", "charge a call-out fee",
     r"call[- ]?out|trip\s+(?:charge|fee)|service\s+call\s+fee|travel\s+fee"),
    ("guarantee", "guarantee", "state a guarantee",
     r"guarantee|money[- ]back|refund|risk[- ]free|or\s+you\s+don'?t\s+pay|or\s+your\s+money"),
    ("limits", "limits", "state limits (caps, seats, area, hours)", r"\S"),
    ("speed", "speed", "say how fast (go live, response, same day)", r"\S"),
    ("includes", "features", "list what each plan includes", r"\S"),
    ("package", "plan names", "name their plans", r"\S"),
]
RISK_REVERSAL = ("free plan", "free trial", "cancel anytime", "guarantee")
_MONTHLY = re.compile(r"\bmonthly\b|month[- ]to[- ]month|per\s+month|/\s?mo(?:nth)?\b", re.I)
_BILLED_YEARLY = re.compile(r"billed\s+(?:annually|yearly|once a year)|paid\s+(?:annually|yearly)|per\s+year|/\s?y(?:ea)?r\b|"
                            r"annual(?:ly)?\b|yearly", re.I)


def as_list(value) -> list:
    if not value:
        return []
    return [value] if isinstance(value, str) else [x for x in value if isinstance(x, str) and x]


def row_tags(row: dict) -> set:
    tags = set()
    for field, tag, _, pattern in TERMS:
        if any(re.search(pattern, v, re.I) for v in as_list(row.get(field))):
            tags.add(tag)
    # "$199/mo, billed annually": the price says how it is billed
    if _BILLED_YEARLY.search(row.get("price_text") or ""):
        tags.add("annual billing")
    if tags & set(RISK_REVERSAL):
        tags.add("risk reversal")
    return tags


def term_summary(rows: list) -> list:
    """For each term: how many competitors state it (in any of their rows), and whether the owner does.
    'annual only' is a competitor that bills yearly with no monthly price and no monthly option stated."""
    by = {}
    for r in rows:
        by.setdefault(r.get("competitor", ""), []).append(r)
    who = sorted(k for k in by if k != "you")
    tags = {k: set().union(*(row_tags(r) for r in by[k])) for k in by}
    for k, rs in by.items():
        monthly = any(r.get("period") == "month" and not _BILLED_YEARLY.search(r.get("price_text") or "")
                      for r in rs) or any(_MONTHLY.search(v) for r in rs for v in as_list(r.get("commitment")))
        if "annual billing" in tags[k] and not monthly:
            tags[k].add("annual only")
    labels = [(tag, label) for _, tag, label, _ in TERMS]
    labels.insert(6, ("annual only", "sell annual only"))
    labels.append(("risk reversal", "take the risk off the buyer (free plan, trial, cancel anytime or guarantee)"))
    out = []
    for tag, label in labels:
        out.append({"tag": tag, "label": label, "count": sum(1 for k in who if tag in tags[k]), "of": len(who),
                    "you": tag in tags.get("you", set()) if "you" in by else None})
    return out


def term_lines(terms: list) -> tuple:
    """('4 of 11 have a free plan', ...), ('none of 11 offer a demo', ...)."""
    said = ["%d of %d %s" % (t["count"], t["of"], t["label"]) for t in terms if t["count"]]
    none = ["none of %d %s" % (t["of"], t["label"]) for t in terms if not t["count"] and t["of"]]
    return said, none


def domain(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"^[a-z]+://", "", url)
    url = url.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    return url[4:] if url.startswith("www.") else url


def median(values: list):
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2.0


def quantile(values: list, q: float):
    v = sorted(values)
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)
