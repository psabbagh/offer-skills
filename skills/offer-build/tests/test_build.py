"""Tests for the offer-build skill. Run: python3 -m unittest discover -s offer-build/tests"""

import contextlib
import filecmp
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
ROOT = os.path.dirname(SKILL)
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import build  # noqa: E402
import offerlib  # noqa: E402

FACTS = {"business": "Acme", "offer_name": "Client Engine",
         "prices": ["$1,500 a month"], "guarantees": ["If you do not sign a new client in 90 days, we refund your last month"],
         "numbers": ["42 agencies coached since 2023"], "limits": ["We take 5 new agencies a month"],
         "deadlines": [], "bonuses": ["the cold email template pack"], "proof": []}

CUSTOMER = {
    "business": "Acme", "target": "owners of small marketing agencies", "category": "agency coaching",
    "budget_period": "month", "offer_price": 1000,
    "segments": [{"name": "solo founders", "share": 0.5, "income": [60000, 120000], "budget": [200, 900]},
                 {"name": "small teams", "share": 0.5, "income": [120000, 300000], "budget": [800, 3000]}],
    "behaviours": [{"name": "asks peers first", "share": 1, "how": "only buys on a referral"}],
    "today": [{"name": "free YouTube videos", "share": 1}],
}


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get(offerlib.LIBRARY_ENV)
        os.environ[offerlib.LIBRARY_ENV] = self.tmp
        self.run_dir = offerlib.new_run("Acme")
        offerlib.write_json(os.path.join(self.run_dir, "run.json"), {"business": "Acme"})
        offerlib.write_json(os.path.join(self.run_dir, "competitors.json"), {"competitors": [
            {"key": "brightpath.example", "name": "Brightpath Coaching", "kind": "online", "found_by": ["search"]}]})
        with open(os.path.join(self.run_dir, "pages.jsonl"), "w") as fh:
            fh.write(json.dumps({"key": "brightpath.example", "url": "https://brightpath.example",
                                 "text": "Land three retainer clients in 90 days. 30-day money-back guarantee."}) + "\n")
            fh.write(json.dumps({"key": "you", "url": "https://acme.example",
                                 "text": "Coaching for agency owners."}) + "\n")

    def tearDown(self):
        if self.old is None:
            os.environ.pop(offerlib.LIBRARY_ENV, None)
        else:
            os.environ[offerlib.LIBRARY_ENV] = self.old
        shutil.rmtree(self.tmp)

    def call(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = build.main(list(argv))
        return code, buf.getvalue()


class Score(Env):
    def test_scores_need_quotes_found_in_evidence(self):
        offerlib.write_json(os.path.join(self.run_dir, "facts.json"), FACTS)
        with open(os.path.join(self.run_dir, "offer-new.md"), "w") as fh:
            fh.write("Sign your next retainer client in 90 days.")
        offerlib.write_json(os.path.join(self.run_dir, "scores.json"), [
            {"competitor": "brightpath.example", "ratings": {
                "outcome": {"score": 3, "quote": "Land three retainer clients in 90 days"},
                "risk": {"score": 2, "quote": "30-day money-back guarantee"},
                "proof": {"score": 3, "quote": "500 agencies served"},
                "speed": {"score": 2}}},
            {"competitor": "you", "ratings": {"outcome": {"score": 1, "quote": "Coaching for agency owners"}}},
            {"competitor": "you-new", "ratings": {
                "outcome": {"score": 3, "quote": "Sign your next retainer client in 90 days"},
                "risk": {"score": 3, "quote": "we refund your last month"},
                "proof": {"score": 2, "quote": "42 agencies coached since 2023"}}},
        ])
        code, out = self.call("score", "--business", "Acme")
        self.assertEqual(code, 0, out)
        card = offerlib.read_json(os.path.join(self.run_dir, "scorecard.json"))
        by = {r["competitor"]: r for r in card["ranked"]}
        self.assertEqual(by["brightpath.example"]["total"], 5, "the made-up proof and the quoteless speed count 0")
        self.assertEqual(by["you-new"]["total"], 8)
        self.assertEqual(by["you-new"]["rank"], 1)
        self.assertEqual(len(card["notes"]), 2)
        self.assertIn("rank 3 of 3", out)

    def test_unknown_competitor_is_an_error(self):
        offerlib.write_json(os.path.join(self.run_dir, "scores.json"), [{"competitor": "nobody", "ratings": {}}])
        self.assertEqual(self.call("score", "--business", "Acme")[0], 2)


class CopyCheck(unittest.TestCase):
    def facts(self):
        f = json.loads(json.dumps(FACTS))
        return f

    def test_approved_copy_passes(self):
        text = ("Client Engine is $1,500 a month.\nIf you do not sign a new client in 90 days, we refund your last month.\n"
                "We take 5 new agencies a month. 42 agencies coached since 2023.\n"
                "You also get the cold email template pack.")
        self.assertEqual(build.check_copy(text, self.facts(), ["Brightpath Coaching"]), [])

    def test_no_false_alarms(self):
        f = self.facts()
        f["guarantees"].append("If your first month does not end with a plan you agree with, you do not pay for it")
        text = ("# Client Engine\n1. Monthly one-on-one coaching.\n2. Plans that drift once the call ends get fixed.\n"
                "- If your first month does not end with a plan you agree with, you do not pay for it.\n"
                "Client Engine costs $1,500/month.")
        self.assertEqual(build.check_copy(text, f, []), [])

    def test_refusals(self):
        bad = {
            "Now only $997 a month.": "price",
            "Double your revenue.": "number",
            "Backed by a 60-day money-back guarantee.": "guarantee",
            "Only 3 spots left.": "limit",
            "Doors close Friday at midnight.": "deadline",
            "Plus a free strategy workbook.": "bonus",
            "Built on Alex Hormozi's ideas.": "endorsement",
            "Better than Brightpath Coaching.": "competitor",
            "Join 300 agencies.": "number",
        }
        for sentence, kind in bad.items():
            problems = build.check_copy(sentence, self.facts(), ["Brightpath Coaching"])
            self.assertIn(kind, [p[1] for p in problems], "%r should be refused as %s" % (sentence, kind))

    def test_command_exit_codes(self):
        tmp = tempfile.mkdtemp()
        old = os.environ.get(offerlib.LIBRARY_ENV)
        os.environ[offerlib.LIBRARY_ENV] = tmp
        try:
            run = offerlib.new_run("Acme")
            offerlib.write_json(os.path.join(run, "facts.json"), FACTS)
            good, bad = os.path.join(tmp, "good.md"), os.path.join(tmp, "bad.md")
            with open(good, "w") as fh:
                fh.write("Client Engine is $1,500 a month.")
            with open(bad, "w") as fh:
                fh.write("Only 2 seats left at $999.")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(build.main(["check-copy", good, "--business", "Acme"]), 0)
                self.assertEqual(build.main(["check-copy", bad, "--business", "Acme"]), 1)
            self.assertIn("REFUSED", buf.getvalue())
        finally:
            if old is None:
                os.environ.pop(offerlib.LIBRARY_ENV, None)
            else:
                os.environ[offerlib.LIBRARY_ENV] = old
            shutil.rmtree(tmp)


class Panel(Env):
    def test_same_buyers_see_both_offers_and_compare(self):
        cpath = os.path.join(self.tmp, "customer.json")
        offerlib.write_json(cpath, CUSTOMER)
        old_p, new_p = os.path.join(self.tmp, "old.md"), os.path.join(self.tmp, "new.md")
        with open(old_p, "w") as fh:
            fh.write("Agency coaching, $1,000 a month.")
        with open(new_p, "w") as fh:
            fh.write("Client Engine: sign a new client in 90 days or we refund your last month. $1,500 a month.")
        code, out = self.call("panel", "--business", "Acme", "--customer", cpath, "--old", old_p, "--new", new_p,
                              "--quick", "--new-price", "1500")
        self.assertEqual(code, 0, out)
        old_cards = offerlib.read_json(os.path.join(self.run_dir, "buyers", "old", "cards.json"))
        new_cards = offerlib.read_json(os.path.join(self.run_dir, "buyers", "new", "cards.json"))
        self.assertEqual(len(old_cards), 20)
        self.assertEqual(old_cards, new_cards)
        new_panel = offerlib.read_json(os.path.join(self.run_dir, "buyers", "new", "panel.json"))
        self.assertEqual(new_panel["customer"]["offer_price"], 1500)
        # stand-in answers, written the way buyer sub-agents write them
        for side, buyers_yes in (("old", 4), ("new", 9)):
            for i, card in enumerate(old_cards):
                ans = {"id": card["id"], "decision": "buy_now" if i < buyers_yes else "no", "first_month": 1,
                       "reason_code": "price", "reason": "test", "objection": "test", "would_change_my_mind": "",
                       "instead": "", "price_too_cheap": 100, "price_bargain": 500, "price_expensive": 1500,
                       "price_too_expensive": 3000}
                offerlib.write_json(os.path.join(self.run_dir, "buyers", side, "answers", card["id"] + ".json"), ans)
        code, out = self.call("compare", "--business", "Acme")
        self.assertEqual(code, 0, out)
        self.assertIn("4 of 20 would buy today with the old offer, 9 of 20 with the new one", out)
        cmp_ = offerlib.read_json(os.path.join(self.run_dir, "buyers", "compare.json"))
        self.assertEqual((len(cmp_["moved_to_buy"]), len(cmp_["stopped_buying"])), (5, 0))


class SharedCopies(unittest.TestCase):
    def test_buyers_is_identical_to_startup_buyers(self):
        original = os.path.join(ROOT, "startup-buyers", "buyers.py")
        if not os.path.exists(original):
            self.skipTest("startup-buyers is not beside this skill")
        self.assertTrue(filecmp.cmp(original, os.path.join(SKILL, "scripts", "buyers.py"), shallow=False),
                        "scripts/buyers.py has drifted from startup-buyers/buyers.py")

    def test_offerlib_is_identical_in_every_skill(self):
        mine = os.path.join(SKILL, "scripts", "offerlib.py")
        for other in ("offer", "offer-price"):
            path = os.path.join(ROOT, other, "scripts", "offerlib.py")
            if os.path.exists(path):
                self.assertTrue(filecmp.cmp(mine, path, shallow=False), "%s has drifted" % path)


if __name__ == "__main__":
    unittest.main()
