"""Tests for the offer skill. Run: python3 -m unittest discover -s offer/tests"""

import contextlib
import filecmp
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
ROOT = os.path.dirname(SKILL)
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import offer  # noqa: E402
import offerlib  # noqa: E402

# Made-up page text in the shape a browser returns for a Meta Ad Library results page.
AD_PAGE = """Ad Library
~1,200 results
Active
Library ID: 111222333
Started running on Oct 3, 2026
Platforms
See ad details
Brightpath Coaching
Sponsored
Run your agency without working weekends.
Our 90-day program costs $1,997 and comes with a 30-day money-back guarantee.
BRIGHTPATH.EXAMPLE
Apply now
Active
Library ID: 444555666
Started running on Nov 1, 2026
Platforms
3 ads use this creative and text
See summary details
Northstar Ops
Sponsored
Free workshop for agency owners. https://northstar.example/workshop
Learn more
Active
Library ID: 777888999
Started running on Nov 2, 2026
See ad details
Brightpath Coaching
Sponsored
Run your agency without working weekends.
Our 90-day program costs $1,997 and comes with a 30-day money-back guarantee.
BRIGHTPATH.EXAMPLE
"""

PRICING_HTML = """<html><head><title>Pricing</title><script>var x = "$999";</script></head><body>
<h1>Coaching plans</h1><h2>Group</h2><p>Group coaching: <b>$497</b>/month</p>
<ul><li>Weekly group call</li><li>Template   library</li></ul>
<p>14-day free trial. Cancel anytime.</p><p>Up to 3 seats</p><p>Onboarding within 48 hours</p>
<p>Private coaching: $2,500 per month</p><p>If you do not land a client in 60 days, we refund you in full.</p>
</body></html>"""
HOME_HTML = """<html><head><title>Home</title></head><body><h1>We coach agency owners</h1>
<a href="/pricing">Pricing</a> <a href="/blog/post">Blog</a> <a href="https://other.example/x">Elsewhere</a>
<p>%s</p></body></html>""" % ("Agency coaching that works. " * 30)


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get(offerlib.LIBRARY_ENV)
        os.environ[offerlib.LIBRARY_ENV] = self.tmp

    def tearDown(self):
        if self.old is None:
            os.environ.pop(offerlib.LIBRARY_ENV, None)
        else:
            os.environ[offerlib.LIBRARY_ENV] = self.old
        shutil.rmtree(self.tmp)

    def run_cmd(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = offer.main(list(argv))
        return code, buf.getvalue()


class Helpers(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(offerlib.parse_amount("$1,500"), (1500.0, "USD"))
        self.assertEqual(offerlib.parse_amount("from €2.5k"), (2500.0, "EUR"))
        self.assertEqual(offerlib.parse_amount("£49.99/mo"), (49.99, "GBP"))
        self.assertEqual(offerlib.parse_amount("1.500,00 EUR"), (1500.0, "EUR"))
        self.assertEqual(offerlib.parse_amount("Call for a quote"), (None, None))

    def test_periods(self):
        self.assertEqual(offerlib.parse_period("", "$497/month"), "month")
        self.assertEqual(offerlib.parse_period("per year", "$4,000"), "year")
        self.assertEqual(offerlib.parse_period("", "$1,997"), "one-time")
        self.assertEqual(offerlib.parse_period("", "$970 / year (2 Mo Free!)"), "year")

    def test_word_for_word(self):
        self.assertTrue(offerlib.found_in("$2,500 per month", "Private coaching:  $2,500\nper Month"))
        self.assertFalse(offerlib.found_in("$2,400 per month", "Private coaching: $2,500 per month"))
        self.assertTrue(offerlib.found_in("30-day guarantee", "a 30–day guarantee"))
        self.assertFalse(offerlib.found_in("", "anything"))

    def test_term_tags_and_counts(self):
        rows = [{"competitor": "a", "free_way_in": ["Free forever plan"], "commitment": ["Billed annually"],
                 "period": "year"},
                {"competitor": "b", "free_way_in": ["14-day free trial"], "commitment": ["Cancel anytime"],
                 "period": "month"},
                {"competitor": "c", "commitment": ["Billed annually or $12 monthly"], "period": "year"},
                {"competitor": "you", "guarantee": "30-day money-back guarantee"}]
        self.assertEqual(offerlib.row_tags(rows[0]), {"free plan", "annual billing", "risk reversal"})
        terms = {t["tag"]: t for t in offerlib.term_summary(rows)}
        self.assertEqual(terms["free plan"]["count"], 1)
        self.assertEqual(terms["annual billing"]["count"], 2)
        self.assertEqual(terms["annual only"]["count"], 1, "c also sells monthly")
        self.assertEqual(terms["risk reversal"]["count"], 2)
        self.assertEqual(terms["guarantee"]["count"], 0)
        self.assertTrue(terms["guarantee"]["you"])
        shown_monthly = [{"competitor": "d", "price_text": "$199/mo, billed annually", "period": "month"}]
        self.assertEqual([t["count"] for t in offerlib.term_summary(shown_monthly) if t["tag"] == "annual only"], [1],
                         "a per-month price billed annually is annual only")
        said, none = offerlib.term_lines(offerlib.term_summary(rows))
        self.assertIn("1 of 3 have a free plan", said)
        self.assertIn("1 of 3 sell annual only", said)
        self.assertIn("none of 3 state a guarantee", none)

    def test_keys(self):
        self.assertEqual(offer.competitor_key("https://www.Acme.example/about"), "acme.example")
        self.assertEqual(offer.competitor_key("https://www.skool.com/agency-club/about"), "skool.com/agency-club")
        self.assertTrue(offer.is_listing("https://www.yelp.com/biz/x"))
        self.assertFalse(offer.is_listing("https://acme.example"))
        self.assertEqual(offer.competitor_key("https://lp.acme.example/vsl"), "acme.example")
        self.assertEqual(offer.competitor_key("https://checkout.acme.example"), "acme.example")
        self.assertEqual(offer.competitor_key("https://acme.example"), "acme.example")

    def test_links_stay_on_the_sellers_path(self):
        links = [("/poe-club/plans", "Plans"), ("/other-group/pricing", "Pricing"), ("/poe-club/about", "About")]
        got = offer.pick_links("https://www.skool.com/poe-club", links, 3, "/poe-club")
        self.assertEqual(got, ["https://www.skool.com/poe-club/plans"])

    def test_platform_ads(self):
        page = ("Library ID: 1\nStarted running on Nov 1, 2026\nSkool with Jane Roe\nSponsored\n"
                "Join my group for agency owners.\nWWW.SKOOL.COM\n"
                "Library ID: 2\nStarted running on Nov 2, 2026\nSam Poe\nSponsored\n"
                "Lock in $17/month: https://www.skool.com/poe-club/about\nSKOOL.COM\n")
        a, b = offer.parse_ads(page)
        self.assertEqual(a["advertiser"], "Jane Roe")
        self.assertEqual(a["sites"], [], "a bare skool.com says nothing about the seller")
        self.assertEqual(b["sites"], ["skool.com/poe-club"])


class Ads(unittest.TestCase):
    def test_parse(self):
        ads = offer.parse_ads(AD_PAGE)
        self.assertEqual(len(ads), 2, "the repeated creative is kept once")
        a, b = ads
        self.assertEqual(a["advertiser"], "Brightpath Coaching")
        self.assertEqual(a["started"], "Oct 3, 2026")
        self.assertEqual(a["sites"], ["brightpath.example"])
        self.assertIn("$1,997", a["text"])
        self.assertEqual(len(a["guarantee_lines"]), 1)
        self.assertEqual(b["advertiser"], "Northstar Ops")
        self.assertEqual(b["sites"], ["northstar.example"])
        self.assertNotIn("Learn more", b["text"])


class Flow(Env):
    def start(self):
        code, out = self.run_cmd("start", "--business", "Acme Coaching", "--site", "acme.example")
        self.assertEqual(code, 0, out)
        return offerlib.runs("Acme Coaching")[-1]

    def test_competitors_merge_and_drop(self):
        run = self.start()
        with open(os.path.join(run, "found.json"), "w") as fh:
            json.dump([
                {"name": "Brightpath", "website": "https://www.brightpath.example/coaching", "kind": "online",
                 "source_url": "https://search.example/1"},
                {"name": "Yelp page", "website": "https://www.yelp.com/biz/x"},
                {"name": "Ourselves", "website": "https://acme.example"},
                {"name": "Agency Club", "website": "https://www.skool.com/agency-club/about"},
                {"name": "Town Coach", "website": "https://towncoach.example", "kind": "local"},
            ], fh)
        ad_file = os.path.join(self.tmp, "ads.txt")
        with open(ad_file, "w") as fh:
            fh.write(AD_PAGE)
        self.assertEqual(self.run_cmd("ads", ad_file, "--run", run)[0], 0)
        code, out = self.run_cmd("competitors", "--run", run, "--drop", "towncoach.example")
        self.assertEqual(code, 0, out)
        comps = offerlib.read_json(os.path.join(run, "competitors.json"))
        keys = [c["key"] for c in comps["competitors"]]
        self.assertEqual(keys, ["brightpath.example", "northstar.example", "skool.com/agency-club"])
        bright = comps["competitors"][0]
        self.assertEqual(sorted(bright["found_by"]), ["ads", "search"])
        self.assertEqual(len(comps["skipped"]), 1)
        # a drop is remembered on the next call, and --keep brings it back
        self.run_cmd("competitors", "--run", run)
        self.assertNotIn("towncoach.example", [c["key"] for c in offerlib.read_json(os.path.join(run, "competitors.json"))["competitors"]])
        self.run_cmd("competitors", "--run", run, "--keep", "towncoach.example")
        self.assertIn("towncoach.example", [c["key"] for c in offerlib.read_json(os.path.join(run, "competitors.json"))["competitors"]])

    def _seed_run(self, run, price="$497", guarantee="we refund you in full", page=PRICING_HTML):
        title, text, _ = offer.html_to_text(page)
        with open(os.path.join(run, "competitors.json"), "w") as fh:
            json.dump({"business": "Acme Coaching", "own_key": "acme.example", "dropped": [], "skipped": [],
                       "competitors": [
                           {"key": "brightpath.example", "name": "Brightpath", "website": "https://brightpath.example",
                            "kind": "online", "found_by": ["search"], "sources": [], "notes": []},
                           {"key": "quietco.example", "name": "Quiet Co", "website": "https://quietco.example",
                            "kind": "online", "found_by": ["search"], "sources": [], "notes": []}]}, fh)
        with open(os.path.join(run, "pages.jsonl"), "w") as fh:
            fh.write(json.dumps({"key": "brightpath.example", "url": "https://brightpath.example/pricing",
                                 "title": title, "text": text, "via": "fetch"}) + "\n")
        with open(os.path.join(run, "offers.json"), "w") as fh:
            json.dump([
                {"competitor": "brightpath.example", "service": "Group coaching", "price_text": price,
                 "unit": "per month", "basis": "published", "source_url": "https://brightpath.example/pricing",
                 "guarantee": guarantee},
                {"competitor": "brightpath.example", "service": "group coaching", "package": "made up",
                 "price_text": "$999", "basis": "published", "source_url": "https://brightpath.example/pricing"},
                {"competitor": "brightpath.example", "service": "group coaching", "package": "other page",
                 "price_text": "$497", "basis": "published", "source_url": "https://brightpath.example/never-read"},
                {"competitor": "you", "service": "group coaching", "price_text": "$300", "unit": "per month",
                 "basis": "owner said"},
            ], fh)

    def test_table_checks_every_price(self):
        run = self.start()
        self._seed_run(run)
        code, out = self.run_cmd("table", "--run", run)
        self.assertEqual(code, 0, out)
        t = offerlib.read_json(os.path.join(run, "table.json"))
        good, made_up, other_page, you, quiet = t["rows"]
        self.assertEqual((good["status"], good["amount"], good["period"]), ("checked", 497.0, "month"))
        self.assertEqual(good["guarantee"], "we refund you in full")
        # $999 sits only inside a <script>, which is not page text: it is not a published price
        self.assertEqual(made_up["price_text"], "")
        self.assertEqual(made_up["package"], "", "a plan name not on the page is cleared too")
        self.assertEqual(other_page["status"], "unknown")
        self.assertEqual(you["status"], "owner said")
        self.assertEqual(quiet["service"], "(nothing found)")
        self.assertEqual(t["summary"]["with_published_price"], 1)
        self.assertEqual(t["summary"]["price_unknown"], 1)
        for name in ("offer-table.md", "offer-table.csv", "offer-table.html", "checks.txt"):
            self.assertTrue(os.path.exists(os.path.join(run, name)), name)
        with open(os.path.join(run, "offer-table.md")) as fh:
            self.assertIn("unknown", fh.read())

    def test_guarantee_not_on_page_is_cleared(self):
        run = self.start()
        self._seed_run(run, guarantee="lifetime guarantee")
        self.run_cmd("table", "--run", run)
        t = offerlib.read_json(os.path.join(run, "table.json"))
        self.assertEqual([r["guarantee"] for r in t["rows"] if r["competitor"] == "brightpath.example"][0], "")

    def test_changes_between_runs(self):
        first = self.start()
        self._seed_run(first)
        self.run_cmd("table", "--run", first)
        second = self.start()
        self.assertTrue(second.endswith("-2"))
        page = PRICING_HTML.replace("$497", "$597").replace("we refund you in full", "")
        self._seed_run(second, price="$597", guarantee="", page=page)
        comps = offerlib.read_json(os.path.join(second, "competitors.json"))
        comps["competitors"].append({"key": "newco.example", "name": "NewCo", "website": "https://newco.example",
                                     "kind": "online", "found_by": ["ads"], "sources": [], "notes": []})
        offerlib.write_json(os.path.join(second, "competitors.json"), comps)
        self.run_cmd("table", "--run", second)
        code, out = self.run_cmd("changes", "--business", "Acme Coaching")
        self.assertEqual(code, 0, out)
        with open(os.path.join(second, "changes.md")) as fh:
            md = fh.read()
        self.assertIn("price raised", md)
        self.assertIn("$497 to $597", md)
        self.assertIn("guarantee dropped", md)
        self.assertIn("new competitor", md)


    # ---------------------------------------------------------------- plans, features and terms

    def _terms_run(self, offers, extra_pages=(), ads=None, comp_ads=None):
        run = self.start()
        self._seed_run(run)
        with open(os.path.join(run, "pages.jsonl"), "a") as fh:
            for key, url, text in extra_pages:
                fh.write(json.dumps({"key": key, "url": url, "title": "", "text": text, "via": "agent"}) + "\n")
        if ads is not None:
            offerlib.write_json(os.path.join(run, "ads.json"), ads)
        if comp_ads:
            comps = offerlib.read_json(os.path.join(run, "competitors.json"))
            for c in comps["competitors"]:
                c["ads"] = comp_ads.get(c["key"], [])
            offerlib.write_json(os.path.join(run, "competitors.json"), comps)
        offerlib.write_json(os.path.join(run, "offers.json"), offers)
        code, out = self.run_cmd("table", "--run", run)
        self.assertEqual(code, 0, out)
        return run, offerlib.read_json(os.path.join(run, "table.json")), out

    GOOD = {"competitor": "brightpath.example", "service": "group coaching", "package": "Group",
            "price_text": "$497", "unit": "per month", "basis": "published",
            "source_url": "https://brightpath.example/pricing"}

    def test_every_plan_feature_and_term_is_checked_word_for_word(self):
        row = dict(self.GOOD, includes=["Weekly group call", "Done-for-you ads"],
                   bonuses=["Template library", "A free laptop"], free_way_in="14-day free trial",
                   commitment=["Cancel anytime", "12-month contract"], limits=["Up to 3 seats", "Unlimited seats"],
                   speed=["Onboarding within 48 hours", "Live in 5 minutes"], guarantee="we refund you in full")
        planted_plan = dict(self.GOOD, package="Platinum")
        run, t, out = self._terms_run([row, planted_plan])
        r, p = t["rows"][0], t["rows"][1]
        self.assertEqual(r["package"], "Group")
        self.assertEqual(r["includes"], ["Weekly group call"], "the planted feature is cleared")
        self.assertEqual(r["bonuses"], ["Template library"])
        self.assertEqual(r["free_way_in"], ["14-day free trial"])
        self.assertEqual(r["commitment"], ["Cancel anytime"])
        self.assertEqual(r["limits"], ["Up to 3 seats"])
        self.assertEqual(r["speed"], ["Onboarding within 48 hours"])
        self.assertEqual(r["guarantee"], "we refund you in full")
        self.assertEqual(p["package"], "", "a plan name not on the page is cleared")
        self.assertEqual(p["status"], "checked", "clearing the plan name leaves the checked price alone")
        for planted in ("feature 'Done-for-you ads'", "extra 'A free laptop'", "commitment '12-month contract'",
                        "limit 'Unlimited seats'", "speed 'Live in 5 minutes'", "plan name 'Platinum'"):
            self.assertIn(planted + " is not on their pages word for word; cleared", out)
        with open(os.path.join(run, "checks.txt")) as fh:
            self.assertEqual(fh.read().count("cleared"), 6)
        with open(os.path.join(run, "offer-table.html")) as fh:
            page = fh.read()
        for shown in ("Free way in", "14-day free trial", "Cancel anytime", "Up to 3 seats", "Onboarding within 48 hours",
                      "Weekly group call", "1 of 2 offer a free trial", "none of 2 have a free plan"):
            self.assertIn(shown, page)
        self.assertNotIn("Done-for-you ads", page)
        with open(os.path.join(run, "offer-table.csv")) as fh:
            self.assertIn("free_way_in", fh.readline())

    def test_a_feature_counts_on_their_other_pages_and_ads_but_not_someone_elses(self):
        ad = {"library_id": "42", "advertiser": "Brightpath", "url": "https://www.facebook.com/ads/library/?id=42",
              "text": "Every plan comes with a private Slack channel.", "sites": ["brightpath.example"]}
        row = dict(self.GOOD, includes=["Unlimited playbooks", "private Slack channel", "Hand-written audits"])
        run, t, out = self._terms_run(
            [row], extra_pages=[("brightpath.example", "https://brightpath.example/features", "Unlimited playbooks"),
                                ("quietco.example", "https://quietco.example/features", "Hand-written audits")],
            ads=[ad], comp_ads={"brightpath.example": ["42"]})
        self.assertEqual(t["rows"][0]["includes"], ["Unlimited playbooks", "private Slack channel"])
        self.assertIn("feature 'Hand-written audits' is not on their pages", out)

    def test_owner_said_is_exempt_and_published_owner_rows_are_checked(self):
        said = {"competitor": "you", "service": "group coaching", "price_text": "$300", "basis": "owner said",
                "includes": ["Two calls a week"], "free_way_in": ["7-day free trial"]}
        published = {"competitor": "you", "service": "private coaching", "price_text": "", "basis": "none",
                     "includes": ["Two calls a week"]}
        run, t, out = self._terms_run([said, published])
        you = [r for r in t["rows"] if r["competitor"] == "you"]
        self.assertEqual(you[0]["includes"], ["Two calls a week"])
        self.assertEqual(you[0]["free_way_in"], ["7-day free trial"])
        self.assertEqual(you[1]["includes"], [], "not owner said: checked against the owner's own pages")

    def test_a_term_must_be_text(self):
        run = self.start()
        self._seed_run(run)
        offerlib.write_json(os.path.join(run, "offers.json"), [dict(self.GOOD, limits=[3])])
        code, out = self.run_cmd("table", "--run", run)
        self.assertEqual(code, 2)
        self.assertIn("limits must be text", out)

    def test_changes_report_features_and_terms(self):
        first = self.start()
        self._seed_run(first)
        offerlib.write_json(os.path.join(first, "offers.json"), [dict(
            self.GOOD, includes=["Weekly group call"], free_way_in="14-day free trial")])
        self.run_cmd("table", "--run", first)
        second = self.start()
        page = PRICING_HTML.replace("14-day free trial", "").replace("</ul>", "<li>Monthly hot seat</li></ul>")
        self._seed_run(second, page=page)
        offerlib.write_json(os.path.join(second, "offers.json"), [dict(
            self.GOOD, includes=["Weekly group call", "Monthly hot seat"], free_way_in="14-day free trial")])
        self.run_cmd("table", "--run", second)
        code, out = self.run_cmd("changes", "--business", "Acme Coaching")
        self.assertEqual(code, 0, out)
        with open(os.path.join(second, "changes.md")) as fh:
            md = fh.read()
        self.assertIn("feature added**: Brightpath. group coaching, Group: 'Monthly hot seat'", md)
        self.assertIn("free way in dropped**: Brightpath. group coaching, Group: was '14-day free trial'", md)

    def test_changes_read_an_older_table_without_terms(self):
        old = {"rows": [{"competitor": "a", "name": "A", "service": "s", "package": "", "amount": 1.0,
                         "price_text": "$1", "period": "month", "guarantee": "", "includes": [], "bonuses": []}]}
        new = {"rows": [dict(old["rows"][0], speed=["Same-day setup"])]}
        self.assertEqual(offer.compare_tables(old, new), [("speed added", "A", "s: 'Same-day setup'")])


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        pages = {"/": HOME_HTML, "/pricing": PRICING_HTML,
                 "/robots.txt": "User-agent: *\nDisallow: /blog/\n"}
        body = pages.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain" if self.path.endswith(".txt") else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class Fetch(Env):
    def test_fetch_reads_home_and_pricing(self):
        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        os.environ[offer.FETCH_BASE_ENV] = "1"
        try:
            self.run_cmd("start", "--business", "Fetch Test", "--site", base + "/nothing-here")
            run = offerlib.runs("Fetch Test")[-1]
            offerlib.write_json(os.path.join(run, "competitors.json"), {
                "business": "Fetch Test", "own_key": "x", "dropped": [], "skipped": [],
                "competitors": [{"key": "local", "name": "Local", "website": base + "/", "kind": "online",
                                 "found_by": ["search"], "sources": [], "notes": []}]})
            code, out = self.run_cmd("fetch", "--run", run, "--delay", "0")
            self.assertEqual(code, 0, out)
            pages = offerlib.read_jsonl(os.path.join(run, "pages.jsonl"))
            urls = sorted(p["url"] for p in pages if p["key"] == "local")
            self.assertEqual(urls, [base + "/", base + "/pricing"])
            pricing = [p for p in pages if p["url"].endswith("/pricing")][0]
            self.assertIn("$2,500 per month", pricing["text"])
            self.assertNotIn("$999", pricing["text"])
            self.run_cmd("evidence", "--run", run)
            with open(os.path.join(run, "evidence.md")) as fh:
                self.assertIn("$497", fh.read())
        finally:
            os.environ.pop(offer.FETCH_BASE_ENV, None)
            srv.shutdown()
            srv.server_close()

    def test_local_addresses_refused_without_test_flag(self):
        self.run_cmd("start", "--business", "Local Refused", "--site", "https://acme.example")
        run = offerlib.runs("Local Refused")[-1]
        offerlib.write_json(os.path.join(run, "competitors.json"), {
            "business": "x", "own_key": "acme.example", "dropped": [], "skipped": [],
            "competitors": [{"key": "l", "name": "L", "website": "http://127.0.0.1:9/", "kind": "online",
                             "found_by": [], "sources": [], "notes": []}]})
        self.run_cmd("fetch", "--run", run, "--only", "l")
        report = offerlib.read_json(os.path.join(run, "fetch-report.json"))
        self.assertTrue(any("local address refused" in f for f in report["failed"]))


class SharedCopies(unittest.TestCase):
    def test_offerlib_is_identical_in_every_skill(self):
        mine = os.path.join(SKILL, "scripts", "offerlib.py")
        for other in ("offer-price", "offer-build"):
            path = os.path.join(ROOT, other, "scripts", "offerlib.py")
            if os.path.exists(path):
                self.assertTrue(filecmp.cmp(mine, path, shallow=False), "%s has drifted from offer's copy" % path)


if __name__ == "__main__":
    unittest.main()
