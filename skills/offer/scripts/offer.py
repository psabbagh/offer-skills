#!/usr/bin/env python3
"""Competitor offer research for the offer skill. Python 3.9+, standard library only.

The only network use is `fetch`, which reads competitors' own public pages, politely: it obeys
robots.txt, waits between requests to the same site, and reads a few pages per site. Nothing
here needs an API key, an account or a paid service.

    offer.py start --business "Acme Coaching" --site https://acme.example      a new dated run in the library
    offer.py ads ads-page.txt [more.txt] [--run R | --business B]              parse Meta Ad Library page text
    offer.py competitors [--drop KEY,KEY] [--keep KEY,KEY] [--run R | --business B]
    offer.py fetch [--pages-per-site 4] [--only KEY,KEY]                        read their sites
    offer.py evidence                                                           prices and guarantees, with sources
    offer.py table                                                              check offers.json word for word
    offer.py changes [--business B] [--against OLDER_RUN]                       what changed since the last run
    offer.py status

The run folder holds everything: found.json (written by the agent from web search), ads.json,
competitors.json, pages.jsonl (fetched) and agent-pages.jsonl (read by the agent's own web
fetch, word for word), offers.json (written by the agent), then table.json, offer-table.md,
offer-table.csv, offer-table.html, checks.txt and changes.md.

The tool never writes a price. A price reaches the table only when its exact words are found in
the page, ad or owner statement the row names as its source. Everything else is unknown.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from offerlib import (OfferError, domain, found_in, library_root, money, new_run, parse_amount,  # noqa: E402
                      parse_period, read_json, read_jsonl, resolve_run, runs, slugify, write_json,
                      write_text)

USER_AGENT = "offer-skill/1.0 (competitor price research; reads public pages only)"
FETCH_BASE_ENV = "OFFER_FETCH_ALLOW_LOCAL"  # tests only: allow fetching from 127.0.0.1
MAX_BYTES = 1500000
TIMEOUT = 15
DELAY = 1.0
THIN = 400  # characters of text below which a site counts as nearly empty

# Sites that list businesses or host opinions about them. They are not competitors.
LISTING_DOMAINS = {
    "yelp.com", "angi.com", "angieslist.com", "thumbtack.com", "facebook.com", "fb.me", "fb.com",
    "instagram.com", "linkedin.com", "youtube.com", "youtu.be", "tiktok.com", "x.com", "twitter.com",
    "reddit.com", "quora.com", "medium.com", "clutch.co", "g2.com", "capterra.com", "trustpilot.com",
    "upwork.com", "fiverr.com", "wikipedia.org", "amazon.com", "google.com", "bbb.org",
    "yellowpages.com", "nextdoor.com", "houzz.com", "tripadvisor.com", "glassdoor.com", "indeed.com",
    "pinterest.com", "bing.com", "duckduckgo.com", "maps.app.goo.gl", "goo.gl", "bit.ly", "linktr.ee",
    "apple.com", "spotify.com", "producthunt.com", "mentorcruise.com", "docs.google.com", "sites.google.com",
    "share.google", "surveymonkey.com", "typeform.com", "scribd.com", "podcasts.apple.com", "podbean.com", "crunchbase.com", "forbes.com", "entrepreneur.com",
}
# Shared hosts where each seller has their own path: the competitor is host + first path part.
PLATFORM_DOMAINS = {"skool.com", "stan.store", "whop.com", "gumroad.com", "patreon.com", "calendly.com",
                    "beacons.ai", "podia.com", "payhip.com"}
PAGE_WORDS = re.compile(
    r"pric|plan|package|service|program|coaching|course|work-with|workwithme|offer|membership|"
    r"join|enrol|enroll|apply|rates|fees|cost|book|consult|mastermind|accelerator|academy|shop|store|"
    r"guarantee|faq", re.I)


# ---------------------------------------------------------------- run helpers

def run_of(a) -> str:
    return resolve_run(getattr(a, "run", None), getattr(a, "business", None))


def run_info(run: str) -> dict:
    return read_json(os.path.join(run, "run.json"))


# Landing-page hosts in front of a business's own site: lp.acme.example is acme.example.
LANDING_PREFIXES = ("lp", "go", "try", "get", "join", "ads", "checkout", "info", "pages", "offer", "offers",
                    "apply", "book", "link", "learn", "start", "hello", "page", "promo", "events", "event")


def competitor_key(url: str) -> str:
    d = domain(url)
    parts = d.split(".")
    if len(parts) > 2 and parts[0] in LANDING_PREFIXES and d not in PLATFORM_DOMAINS:
        d = ".".join(parts[1:])
    if d in PLATFORM_DOMAINS:
        path = re.sub(r"^[a-z]+://[^/]+", "", (url or "").strip(), flags=re.I).strip("/").split("/")[0]
        path = path.split("?")[0].split("#")[0].lower()
        return d + "/" + path if path else d
    return d


def is_listing(url: str) -> bool:
    d = domain(url)
    return any(d == x or d.endswith("." + x) for x in LISTING_DOMAINS)


# ---------------------------------------------------------------- start

def cmd_start(a):
    site = a.site.strip()
    if not re.match(r"^https?://", site):
        site = "https://" + site
    run = new_run(a.business)
    previous = [r for r in runs(a.business) if r != run]
    info = {"business": a.business, "slug": slugify(a.business), "site": site, "own_key": competitor_key(site),
            "started": datetime.date.today().isoformat(), "previous_run": previous[-1] if previous else None}
    write_json(os.path.join(run, "run.json"), info)
    print("run folder: %s" % run)
    if previous:
        print("previous run: %s (offer.py changes will compare the two)" % previous[-1])
    return 0


# ---------------------------------------------------------------- Meta Ad Library page text

_AD_NOISE = re.compile(
    r"^(active|inactive|platforms|eu transparency|open dropdown|see ad details|see summary details|"
    r"categories|this ad has multiple versions|\d+ ads? use(s)? this creative and text|sponsored|"
    r"library id:.*|started running on.*|\d+:\d+ / \d+:\d+(:\d+)?|\u200b|learn more|shop now|apply now|"
    r"sign up|book now|watch more|see more|get offer|download|subscribe|contact us|send message)$", re.I)
_LANDING = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/\S*)?$", re.I)
_URL_IN_TEXT = re.compile(r"https?://[^\s)>\]\"']+|\b(?:[a-z0-9-]+\.)+(?:com|co|io|ai|net|org|app|coach|"
                          r"academy|store|shop|uk|ca|au|de|fr)(?:/[^\s)>\]\"']*)?", re.I)
_GUARANTEE = re.compile(r"guarantee|money[- ]back|refund|risk[- ]free|or you don'?t pay|or your money", re.I)


def parse_ads(text: str) -> list:
    """Ads from the text of a Meta Ad Library results page, as a browser's get-page-text returns it."""
    lines = [ln.strip() for ln in text.splitlines()]
    starts = [i for i, ln in enumerate(lines) if re.match(r"^Library ID:\s*\d+", ln)]
    ads = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunk = lines[i:end]
        lib_id = re.search(r"\d+", chunk[0]).group(0)
        started = ""
        for ln in chunk[:6]:
            m = re.match(r"^Started running on (.+)$", ln)
            if m:
                started = m.group(1).strip()
        try:
            sp = chunk.index("Sponsored")
        except ValueError:
            continue
        advertiser = ""
        for back in range(sp - 1, 0, -1):
            if chunk[back] and not _AD_NOISE.match(chunk[back]):
                advertiser = chunk[back]
                break
        # a platform running ads for its sellers names itself first: "Skool with Jane Doe"
        advertiser = re.sub(r"^(skool|kajabi|stan|whop) with ", "", advertiser, flags=re.I)
        body, landing = [], []
        for ln in chunk[sp + 1:]:
            if not ln or _AD_NOISE.match(ln):
                continue
            if _LANDING.match(ln) and (ln.isupper() or ln.lower().startswith("http")):
                landing.append(ln.lower())
                continue
            body.append(ln)
        # the trailing "Active"/"Inactive" of the next ad was skipped as noise
        text_body = "\n".join(body).strip()
        urls = [u.lower() for u in _URL_IN_TEXT.findall(text_body)] + landing
        sites = []
        for u in urls:
            if is_listing(u):
                continue
            site = competitor_key(u if re.match(r"^https?://", u) else "https://" + u)
            if domain(site) in PLATFORM_DOMAINS and "/" not in site:
                continue  # a shared host with no seller path says nothing about who the seller is
            if site and site not in sites:
                sites.append(site)
        ads.append({
            "library_id": lib_id,
            "url": "https://www.facebook.com/ads/library/?id=%s" % lib_id,
            "advertiser": advertiser,
            "started": started,
            "sites": sites,
            "text": text_body,
            "guarantee_lines": [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text_body) if _GUARANTEE.search(s)],
        })
    # the same creative is often listed many times
    seen, unique = set(), []
    for ad in ads:
        k = (ad["advertiser"].lower(), re.sub(r"\W+", "", ad["text"].lower())[:400])
        if k in seen:
            continue
        seen.add(k)
        unique.append(ad)
    return unique


def cmd_ads(a):
    run = run_of(a)
    path = os.path.join(run, "ads.json")
    existing = read_json(path, default=[])
    ids = {x["library_id"] for x in existing}
    added = 0
    for f in a.files:
        with open(f, encoding="utf-8") as fh:
            for ad in parse_ads(fh.read()):
                if ad["library_id"] in ids:
                    continue
                ad["query_file"] = os.path.basename(f)
                existing.append(ad)
                ids.add(ad["library_id"])
                added += 1
    write_json(path, existing)
    advertisers = sorted({x["advertiser"] for x in existing if x["advertiser"]})
    with_g = sum(1 for x in existing if x["guarantee_lines"])
    print("%d new ads (%d in all) from %d advertisers; %d mention a guarantee or refund" % (
        added, len(existing), len(advertisers), with_g))
    print("saved to %s" % path)
    return 0


# ---------------------------------------------------------------- competitors

def cmd_competitors(a):
    run = run_of(a)
    info = run_info(run)
    found = read_json(os.path.join(run, "found.json"), default=[])
    ads = read_json(os.path.join(run, "ads.json"), default=[])
    drops_path = os.path.join(run, "dropped.json")
    dropped = set(read_json(drops_path, default=[]))
    for k in (a.drop or "").split(","):
        if k.strip():
            dropped.add(k.strip().lower())
    for k in (a.keep or "").split(","):
        dropped.discard(k.strip().lower())
    write_json(drops_path, sorted(dropped))

    comps, skipped = {}, []
    for f in found:
        site = (f.get("website") or "").strip()
        if not f.get("name") and not site:
            raise OfferError("every entry in found.json needs a name or a website")
        if site and not re.match(r"^https?://", site):
            site = "https://" + site
        if site and is_listing(site):
            skipped.append("%s (%s is a listing site, not a competitor)" % (f.get("name") or site, domain(site)))
            continue
        key = competitor_key(site) if site else "name:" + slugify(f["name"])
        entry = comps.setdefault(key, {"key": key, "name": f.get("name") or key, "website": site,
                                       "kind": f.get("kind") or "online", "found_by": [], "sources": [],
                                       "notes": []})
        by = f.get("found_by") or "search"
        if by not in entry["found_by"]:
            entry["found_by"].append(by)
        if f.get("source_url") and f["source_url"] not in entry["sources"]:
            entry["sources"].append(f["source_url"])
        if f.get("note"):
            entry["notes"].append(f["note"])
        if f.get("kind") == "local":
            entry["kind"] = "local"
    for ad in ads:
        if ad["sites"]:
            site = "https://" + ad["sites"][0]
            key = ad["sites"][0]
        elif ad["advertiser"]:
            site, key = "", "name:" + slugify(ad["advertiser"])
        else:
            continue
        entry = comps.setdefault(key, {"key": key, "name": ad["advertiser"] or key, "website": site,
                                       "kind": "online", "found_by": [], "sources": [], "notes": []})
        if "ads" not in entry["found_by"]:
            entry["found_by"].append("ads")
        entry.setdefault("ads", []).append(ad["library_id"])
    own = info.get("own_key")
    if own in comps:
        del comps[own]
    kept = [c for k, c in sorted(comps.items()) if k not in dropped]
    out = {"business": info["business"], "own_key": own, "competitors": kept, "dropped": sorted(dropped),
           "skipped": skipped}
    write_json(os.path.join(run, "competitors.json"), out)
    local = sum(1 for c in kept if c["kind"] == "local")
    by_ads = sum(1 for c in kept if "ads" in c["found_by"])
    no_site = sum(1 for c in kept if not c["website"])
    print("%d competitors: %d online, %d local; %d found through ads; %d without a website yet" % (
        len(kept), len(kept) - local, local, by_ads, no_site))
    for c in kept[:15]:
        print("  %-38s %-7s %s" % (c["key"][:38], c["kind"], c["name"][:50]))
    if len(kept) > 15:
        print("  ... and %d more in competitors.json" % (len(kept) - 15))
    if skipped:
        print("left out %d listing-site results" % len(skipped))
    return 0


# ---------------------------------------------------------------- fetch

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "header", "footer", "table", "blockquote", "dt", "dd", "button", "label"}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.parts, self.links, self.skip, self.title, self._in_title = [], [], 0, "", False
        self._href, self._anchor = None, []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor).strip()))
            self._href = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data.strip())

    def text(self):
        t = "".join(self.parts)
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t)
        return t.strip()


def html_to_text(raw: str):
    p = _Text()
    try:
        p.feed(raw)
        p.close()
    except Exception:  # broken markup still gives what was parsed so far
        pass
    return p.title.strip(), p.text(), p.links


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Python before 3.11 does not follow 308 Permanent Redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code == 308:
            code = 307
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, code, msg, headers)


_OPENER = urllib.request.build_opener(_Redirects())


class Fetcher:
    def __init__(self, delay=DELAY):
        self.robots, self.last, self.delay = {}, {}, delay

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        base = "%s://%s" % (parts.scheme, parts.netloc)
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": USER_AGENT})
                with _OPENER.open(req, timeout=TIMEOUT) as r:
                    rp.parse(r.read(200000).decode("utf-8", "replace").splitlines())
            except urllib.error.HTTPError as e:
                # no robots.txt means no rules; a server error means try later, so read nothing now
                rp.parse(["User-agent: *", "Disallow: /"] if e.code >= 500 else [])
            except Exception:
                rp.parse([])
            self.robots[base] = rp
        return self.robots[base].can_fetch(USER_AGENT, url)

    def get(self, url):
        host = urllib.parse.urlsplit(url).netloc
        wait = self.last.get(host, 0) + self.delay - time.time()
        if wait > 0:
            time.sleep(wait)
        self.last[host] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5",
                                                   "Accept-Language": "en"})
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                raise OfferError("not a web page (%s)" % ctype)
            raw = r.read(MAX_BYTES)
            charset = r.headers.get_content_charset() or "utf-8"
            return r.geturl(), raw.decode(charset, "replace")


def _local(url):
    return urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "localhost", "::1")


def pick_links(base_url, links, want, prefix=""):
    """Up to `want` links on the same site that look like offer pages. On a shared host
    (skool.com/<group>) only links under the seller's own path count."""
    base = urllib.parse.urlsplit(base_url)
    scored = []
    for href, anchor in links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urllib.parse.urljoin(base_url, href).split("#")[0]
        p = urllib.parse.urlsplit(full)
        if p.scheme not in ("http", "https") or domain(p.netloc) != domain(base.netloc):
            continue
        if prefix and not p.path.lower().startswith(prefix):
            continue
        if re.search(r"\.(pdf|jpg|jpeg|png|gif|zip|mp4|mp3|webp|svg)$", p.path, re.I):
            continue
        if re.search(r"/(blog|news|podcast|careers|jobs|privacy|terms|cookie|login|signin|cart|author|tag)", p.path, re.I):
            continue
        hit = PAGE_WORDS.search(p.path + " " + anchor)
        if not hit:
            continue
        score = 3 if re.search(r"pric|plan|package|rates|fees|cost", p.path + " " + anchor, re.I) else 1
        scored.append((score, full))
    out = []
    for _, url in sorted(scored, key=lambda x: -x[0]):
        if url.rstrip("/") != base_url.rstrip("/") and url not in out:
            out.append(url)
        if len(out) >= want:
            break
    return out


def cmd_fetch(a):
    run = run_of(a)
    comps = read_json(os.path.join(run, "competitors.json"))["competitors"]
    info = run_info(run)
    targets = [{"key": "you", "website": info["site"], "name": info["business"]}] + comps
    only = {k.strip() for k in (a.only or "").split(",") if k.strip()}
    if only:
        targets = [c for c in targets if c["key"] in only]
    pages_path = os.path.join(run, "pages.jsonl")
    have = {(p["key"], p["url"]) for p in read_jsonl(pages_path)}
    fetcher = Fetcher(delay=a.delay)
    today = datetime.date.today().isoformat()
    thin, failed, read_n = [], [], 0
    with open(pages_path, "a", encoding="utf-8") as out:
        for c in targets:
            site = c.get("website")
            if not site:
                continue
            if _local(site) and not os.environ.get(FETCH_BASE_ENV):
                failed.append("%s: local address refused" % c["key"])
                continue
            total, queue, done = 0, [site], set()
            while queue and len(done) < a.pages_per_site:
                url = queue.pop(0)
                if url in done:
                    continue
                done.add(url)
                if (c["key"], url) in have:
                    continue
                try:
                    if not fetcher.allowed(url):
                        failed.append("%s: robots.txt asks tools not to read %s" % (c["key"], url))
                        continue
                    final, raw = fetcher.get(url)
                except Exception as e:  # one bad page never stops the run
                    failed.append("%s: %s (%s)" % (c["key"], url, str(e)[:80]))
                    continue
                title, text, links = html_to_text(raw)
                if (c["key"], final) in have:
                    continue
                rec = {"key": c["key"], "url": final, "title": title, "fetched": today, "via": "fetch", "text": text}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                have.add((c["key"], final))
                total += len(text)
                read_n += 1
                if url == site:
                    prefix = "/" + c["key"].split("/", 1)[1] if "/" in c["key"] else ""
                    queue.extend(pick_links(final, links, a.pages_per_site - 1, prefix))
            if total < THIN:
                thin.append(c["key"])
    write_json(os.path.join(run, "fetch-report.json"), {"thin": thin, "failed": failed, "date": today})
    print("read %d pages; %d sites came back nearly empty, %d pages failed" % (read_n, len(thin), len(failed)))
    if thin:
        print("nearly empty (read these with your own web fetch, word for word, into agent-pages.jsonl):")
        for k in thin:
            print("  " + k)
    return 0


# ---------------------------------------------------------------- sources

def sources(run: str) -> dict:
    """Every text a price may be checked against: url -> {key, text, via}."""
    out = {}
    for p in read_jsonl(os.path.join(run, "pages.jsonl")) + read_jsonl(os.path.join(run, "agent-pages.jsonl")):
        if not p.get("url") or not p.get("text"):
            continue
        prev = out.get(p["url"])
        out[p["url"]] = {"key": p.get("key", ""), "text": (prev["text"] + "\n" if prev else "") + p["text"],
                         "via": p.get("via", "agent"), "title": p.get("title", "")}
    for ad in read_json(os.path.join(run, "ads.json"), default=[]):
        out[ad["url"]] = {"key": "ad:" + ad["library_id"], "text": ad["advertiser"] + "\n" + ad["text"],
                          "via": "ad", "title": "Meta Ad Library: " + ad["advertiser"]}
    return out


_PRICE_LINE = re.compile(r"(us\$|ca\$|a\$|\$|€|£)\s?\d|\d\s?(usd|eur|gbp)\b|\bfree\b|/\s?mo\b|per month", re.I)


def cmd_evidence(a):
    run = run_of(a)
    comps = read_json(os.path.join(run, "competitors.json"))
    src = sources(run)
    by_key = {}
    for url, s in src.items():
        by_key.setdefault(s["key"], []).append((url, s))
    ads_by_id = {ad["library_id"]: ad for ad in read_json(os.path.join(run, "ads.json"), default=[])}
    lines = ["# Evidence: %s" % comps["business"], "",
             "Lines that hold a price or a guarantee, with the page they came from. Copy prices into "
             "offers.json exactly as written here.", ""]
    for c in [{"key": "you", "name": "you (the owner)"}] + comps["competitors"]:
        lines.append("## %s (%s)" % (c["name"], c["key"]))
        pages = by_key.get(c["key"], [])
        for lib in c.get("ads", []):
            ad = ads_by_id.get(lib)
            if ad:
                pages.append((ad["url"], {"text": ad["text"], "title": "ad"}))
        if not pages:
            lines += ["(nothing read yet)", ""]
            continue
        for url, s in pages:
            hits = []
            for ln in s["text"].splitlines():
                ln = ln.strip()
                if ln and len(ln) < 400 and (_PRICE_LINE.search(ln) or _GUARANTEE.search(ln)) and ln not in hits:
                    hits.append(ln)
            lines.append("- %s %s" % (url, "(%d lines)" % len(hits) if hits else "(no price or guarantee seen)"))
            for h in hits[:25]:
                lines.append("    > " + h)
        lines.append("")
    path = os.path.join(run, "evidence.md")
    write_text(path, "\n".join(lines) + "\n")
    print("wrote %s" % path)
    return 0


# ---------------------------------------------------------------- the checked table

BASES = ("published", "ad", "owner said", "none")


def check_offers(run: str):
    info = run_info(run)
    comps = read_json(os.path.join(run, "competitors.json"))
    names = {c["key"]: c for c in comps["competitors"]}
    offers = read_json(os.path.join(run, "offers.json"))
    if not isinstance(offers, list):
        raise OfferError("offers.json must be a list of rows")
    src = sources(run)
    checks, rows = [], []
    for i, o in enumerate(offers, 1):
        key = (o.get("competitor") or "").strip()
        where = "row %d (%s, %s)" % (i, key or "?", o.get("service") or "?")
        if key != "you" and key not in names:
            raise OfferError("%s: competitor %r is not in competitors.json; use its key" % (where, key))
        basis = (o.get("basis") or "none").strip()
        if basis not in BASES:
            raise OfferError("%s: basis must be one of %s" % (where, ", ".join(BASES)))
        price_text = (o.get("price_text") or "").strip()
        url = (o.get("source_url") or "").strip()
        row = {"competitor": key, "name": info["business"] if key == "you" else names[key]["name"],
               "kind": "you" if key == "you" else names[key]["kind"],
               "service": (o.get("service") or "").strip().lower(), "package": (o.get("package") or "").strip(),
               "price_text": price_text, "unit": (o.get("unit") or "").strip(), "basis": basis,
               "source_url": url, "guarantee": (o.get("guarantee") or "").strip(),
               "includes": list(o.get("includes") or []), "bonuses": list(o.get("bonuses") or []),
               "status": "unknown", "amount": None, "currency": None, "period": "", "note": ""}
        if not row["service"]:
            raise OfferError("%s: every row needs a service" % where)
        page = src.get(url, {}).get("text", "")
        if basis == "none" or not price_text:
            if price_text:
                checks.append("%s: a price with basis none was cleared (%r)" % (where, price_text))
            row.update(price_text="", basis="none")
        elif basis == "owner said":
            if key != "you":
                checks.append("%s: 'owner said' is only for the owner's own prices; set to unknown" % where)
                row.update(price_text="", basis="none")
            else:
                row["status"] = "owner said"
        elif not url:
            checks.append("%s: %r has no source_url; set to unknown" % (where, price_text))
            row.update(price_text="", basis="none")
        elif url not in src:
            checks.append("%s: %s was never read in this run; %r set to unknown" % (where, url, price_text))
            row.update(price_text="", basis="none")
        elif basis == "ad" and src[url]["via"] != "ad":
            checks.append("%s: basis 'ad' needs an Ad Library link from ads.json; set to unknown" % where)
            row.update(price_text="", basis="none")
        elif not found_in(price_text, page):
            checks.append("%s: %r is not on %s word for word; set to unknown" % (where, price_text, url))
            row.update(price_text="", basis="none")
        else:
            row["status"] = "checked"
        if row["price_text"]:
            amount, cur = parse_amount(row["price_text"])
            if amount is None and not re.search(r"\bfree\b", row["price_text"], re.I):
                checks.append("%s: %r holds no amount; kept as text only" % (where, row["price_text"]))
            row["amount"] = 0.0 if amount is None and re.search(r"\bfree\b", row["price_text"], re.I) else amount
            row["currency"] = cur or info.get("currency")
            row["period"] = parse_period(row["unit"], row["price_text"])
        if row["guarantee"]:
            pool = page + "\n" + "\n".join(s["text"] for s in src.values() if s["key"] == key)
            if not (key == "you" and basis == "owner said") and not found_in(row["guarantee"], pool):
                checks.append("%s: guarantee %r is not on their pages word for word; cleared" % (where, row["guarantee"]))
                row["guarantee"] = ""
        rows.append(row)
    # "Free" carries no currency sign: give it the currency the rest of the table uses
    cur_counts = {}
    for r in rows:
        if r["currency"] and r["status"] != "unknown":
            cur_counts[r["currency"]] = cur_counts.get(r["currency"], 0) + 1
    if cur_counts:
        main_cur = max(cur_counts, key=cur_counts.get)
        for r in rows:
            if r["amount"] == 0.0 and not r["currency"]:
                r["currency"] = main_cur
    listed = {r["competitor"] for r in rows}
    for k, c in names.items():
        if k not in listed:
            rows.append({"competitor": k, "name": c["name"], "kind": c["kind"], "service": "(nothing found)",
                         "package": "", "price_text": "", "unit": "", "basis": "none", "source_url": "",
                         "guarantee": "", "includes": [], "bonuses": [], "status": "unknown", "amount": None,
                         "currency": None, "period": "", "note": "no offer found on what was read"})
    return info, comps, rows, checks


def summary(comps, rows) -> dict:
    keys = [c["key"] for c in comps["competitors"]]
    priced = {r["competitor"] for r in rows if r["status"] == "checked"}
    guaranteed = {r["competitor"] for r in rows if r["guarantee"] and r["competitor"] != "you"}
    return {
        "competitors": len(keys),
        "online": sum(1 for c in comps["competitors"] if c["kind"] != "local"),
        "local": sum(1 for c in comps["competitors"] if c["kind"] == "local"),
        "found_by_search": sum(1 for c in comps["competitors"] if "search" in c["found_by"]),
        "found_by_ads": sum(1 for c in comps["competitors"] if "ads" in c["found_by"]),
        "with_published_price": len(priced - {"you"}),
        "price_unknown": len(set(keys) - priced),
        "with_guarantee": len(guaranteed),
        "offer_rows": sum(1 for r in rows if r["competitor"] != "you" and r["service"] != "(nothing found)"),
    }


def cmd_table(a):
    run = run_of(a)
    info, comps, rows, checks = check_offers(run)
    s = summary(comps, rows)
    write_json(os.path.join(run, "table.json"), {"business": info["business"], "run": os.path.basename(run),
                                                 "date": info["started"], "summary": s, "rows": rows})
    write_text(os.path.join(run, "checks.txt"), "\n".join(checks) + ("\n" if checks else ""))
    _write_csv(os.path.join(run, "offer-table.csv"), rows)
    write_text(os.path.join(run, "offer-table.md"), _table_md(info, s, rows))
    write_text(os.path.join(run, "offer-table.html"), _table_html(info, s, rows))
    print("%d competitors (%d online, %d local); %d publish a price we checked word for word, %d unknown; "
          "%d state a guarantee" % (s["competitors"], s["online"], s["local"], s["with_published_price"],
                                    s["price_unknown"], s["with_guarantee"]))
    print("%d checks changed or cleared something (see checks.txt)" % len(checks))
    for c in checks[:20]:
        print("  " + c)
    print("table: %s" % os.path.join(run, "offer-table.html"))
    return 0


COLUMNS = ["name", "competitor", "kind", "service", "package", "price_text", "period", "basis", "status",
           "guarantee", "includes", "bonuses", "source_url"]


def _cell(r, k):
    v = r.get(k)
    if isinstance(v, list):
        return "; ".join(v)
    if k == "price_text" and not v:
        return "unknown"
    return "" if v is None else str(v)


def _write_csv(path, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([_cell(r, k) for k in COLUMNS])
    write_text(path, buf.getvalue())


def _table_md(info, s, rows):
    out = ["# Competitor offers: %s" % info["business"], "",
           "Run of %s. %d competitors (%d online, %d local), %d publish a price checked word for word against "
           "its source, %d unknown. Unknown means nobody published it where we looked; it is not cheap or "
           "expensive." % (info["started"], s["competitors"], s["online"], s["local"], s["with_published_price"],
                           s["price_unknown"]), "",
           "| Who | Service | Package | Price | Guarantee | Source |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["competitor"] != "you", r["service"], r["amount"] is None, r["amount"] or 0)):
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            r["name"].replace("|", "/"), r["service"], r["package"].replace("|", "/"),
            (r["price_text"] or "unknown").replace("|", "/"), r["guarantee"].replace("|", "/") or "",
            r["source_url"] or ""))
    return "\n".join(out) + "\n"


def _table_html(info, s, rows):
    esc = html.escape
    body = []
    for r in sorted(rows, key=lambda r: (r["competitor"] != "you", r["service"], r["amount"] is None, r["amount"] or 0)):
        src = '<a href="%s">source</a>' % esc(r["source_url"]) if r["source_url"] else ""
        body.append("<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                    "<td>%s</td><td>%s</td></tr>" % (
                        "you" if r["competitor"] == "you" else "", esc(r["name"]), esc(r["kind"]), esc(r["service"]),
                        esc(r["package"]), esc(r["price_text"] or "unknown"), esc(r["guarantee"]),
                        esc("; ".join(r["includes"] + r["bonuses"])), src))
    return """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Competitor offers</title>
<style>body{font:14px/1.45 system-ui,sans-serif;margin:16px;color:#1c1c1c;background:#fff}
table{border-collapse:collapse;width:100%%}td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left;vertical-align:top}
tr.you{background:#fff6d6}th{position:sticky;top:0;background:#f4f4f4}.wrap{overflow-x:auto}
@media(prefers-color-scheme:dark){body{background:#151515;color:#eee}th{background:#262626}tr.you{background:#3a3214}td,th{border-color:#333}a{color:#8ab4f8}}</style>
<h1>Competitor offers: %s</h1>
<p>Run of %s. %d competitors (%d online, %d local). %d publish a price checked word for word against its source;
%d unknown. Unknown means nobody published it where we looked.</p>
<div class="wrap"><table><tr><th>Who</th><th>Kind</th><th>Service</th><th>Package</th><th>Price</th><th>Guarantee</th>
<th>Includes and extras</th><th>Source</th></tr>
%s
</table></div>
""" % (esc(info["business"]), esc(info["started"]), s["competitors"], s["online"], s["local"],
       s["with_published_price"], s["price_unknown"], "\n".join(body))


# ---------------------------------------------------------------- changes between runs

def compare_tables(old: dict, new: dict) -> list:
    def index(t):
        comps, offers = {}, {}
        for r in t["rows"]:
            comps.setdefault(r["competitor"], r["name"])
            if r["service"] == "(nothing found)":
                continue
            offers[(r["competitor"], r["service"], r["package"].lower())] = r
        return comps, offers

    oc, oo = index(old)
    nc, no = index(new)
    out = []
    for k in sorted(set(nc) - set(oc)):
        out.append(("new competitor", nc[k], ""))
    for k in sorted(set(oc) - set(nc)):
        out.append(("gone", oc[k], "not found this time"))
    for k in sorted(set(oo) & set(no)):
        a, b = oo[k], no[k]
        label = "%s, %s" % (b["service"], b["package"]) if b["package"] else b["service"]
        if a["amount"] is not None and b["amount"] is not None and a["amount"] != b["amount"] \
                and a.get("period") == b.get("period"):
            word = "price raised" if b["amount"] > a["amount"] else "price lowered"
            out.append((word, b["name"], "%s: %s to %s" % (label, a["price_text"], b["price_text"])))
        elif a["amount"] is None and b["amount"] is not None:
            out.append(("price now published", b["name"], "%s: %s" % (label, b["price_text"])))
        elif a["amount"] is not None and b["amount"] is None:
            out.append(("price no longer published", b["name"], "%s: was %s" % (label, a["price_text"])))
        if a["guarantee"] and not b["guarantee"]:
            out.append(("guarantee dropped", b["name"], "%s: was %r" % (label, a["guarantee"])))
        elif b["guarantee"] and not a["guarantee"]:
            out.append(("guarantee added", b["name"], "%s: %r" % (label, b["guarantee"])))
        elif a["guarantee"] and b["guarantee"] and a["guarantee"] != b["guarantee"]:
            out.append(("guarantee changed", b["name"], "%s: %r to %r" % (label, a["guarantee"], b["guarantee"])))
    for k in sorted(set(no) - set(oo)):
        if k[0] in oc:
            b = no[k]
            out.append(("new offer", b["name"], "%s %s %s" % (b["service"], b["package"], b["price_text"] or "")))
    for k in sorted(set(oo) - set(no)):
        if k[0] in nc:
            a = oo[k]
            out.append(("offer gone", a["name"], "%s %s" % (a["service"], a["package"])))
    return out


def cmd_changes(a):
    run = run_of(a)
    info = run_info(run)
    if a.against:
        older = resolve_run(a.against, None)
    else:
        ordered = runs(info["business"])
        upto = ordered[:ordered.index(run)] if run in ordered else ordered
        before = [r for r in upto if os.path.exists(os.path.join(r, "table.json"))]
        if not before:
            print("no earlier run with a table to compare against")
            return 0
        older = before[-1]
    old = read_json(os.path.join(older, "table.json"))
    new = read_json(os.path.join(run, "table.json"))
    found = compare_tables(old, new)
    lines = ["# What changed: %s" % info["business"], "",
             "From the run of %s to the run of %s." % (old["date"], new["date"]), ""]
    if not found:
        lines.append("Nothing changed in what was found.")
    for kind, who, detail in found:
        lines.append("- **%s**: %s%s" % (kind, who, (". " + detail) if detail else ""))
    path = os.path.join(run, "changes.md")
    write_text(path, "\n".join(lines) + "\n")
    print("%d changes since %s; wrote %s" % (len(found), old["date"], path))
    for kind, who, detail in found[:25]:
        print("  %s: %s %s" % (kind, who, detail))
    return 0


def cmd_status(a):
    root = library_root()
    print("library: %s" % root)
    if a.business:
        for r in runs(a.business):
            t = os.path.join(r, "table.json")
            if os.path.exists(t):
                s = read_json(t)["summary"]
                print("  %s  %d competitors, %d priced" % (os.path.basename(r), s["competitors"], s["with_published_price"]))
            else:
                print("  %s  (no table yet)" % os.path.basename(r))
    elif os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if os.path.isdir(os.path.join(root, name)):
                print("  %s (%d runs)" % (name, len(runs(name))))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("--run")
        sp.add_argument("--business")
        sp.set_defaults(fn=fn)
        return sp

    s = sub.add_parser("start")
    s.add_argument("--business", required=True)
    s.add_argument("--site", required=True)
    s.set_defaults(fn=cmd_start)
    add("ads", cmd_ads).add_argument("files", nargs="+")
    c = add("competitors", cmd_competitors)
    c.add_argument("--drop")
    c.add_argument("--keep")
    f = add("fetch", cmd_fetch)
    f.add_argument("--pages-per-site", type=int, default=4)
    f.add_argument("--only")
    f.add_argument("--delay", type=float, default=DELAY)
    add("evidence", cmd_evidence)
    add("table", cmd_table)
    add("changes", cmd_changes).add_argument("--against")
    add("status", cmd_status)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except OfferError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
