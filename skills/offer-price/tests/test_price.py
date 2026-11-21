"""Tests for the offer-price skill. Run: python3 -m unittest discover -s offer-price/tests"""

import contextlib
import filecmp
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
ROOT = os.path.dirname(SKILL)
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import offerlib  # noqa: E402
import price  # noqa: E402

NUMBERS = os.path.join(SKILL, "tests", "numbers.sample.json")


def row(comp, service, amount, status="checked", period="month", text=None, cur="USD"):
    return {"competitor": comp, "name": comp, "kind": "online", "service": service, "package": "",
            "price_text": text if text is not None else ("$%d" % amount if amount is not None else ""),
            "unit": "", "basis": "published" if amount is not None else "none", "source_url": "https://x.example",
            "guarantee": "", "includes": [], "bonuses": [], "status": status if amount is not None else "unknown",
            "amount": amount, "currency": cur if amount is not None else None, "period": period if amount is not None else "",
            "note": ""}


def table(you=300.0):
    rows = [row("a", "coaching", 400.0), row("b", "coaching", 500.0), row("c", "coaching", 900.0),
            row("d", "coaching", 1200.0), row("e", "coaching", None), row("f", "coaching", 5000.0, period="one-time"),
            row("g", "coaching", 450.0, status="unknown")]
    if you is not None:
        r = row("you", "coaching", you)
        r["status"] = "owner said"
        rows.append(r)
    return {"business": "Acme", "rows": rows}


class Position(unittest.TestCase):
    def test_only_checked_comparable_prices_count(self):
        gs = price.groups(table())
        monthly = [g for g in gs if g["period"] == "month"][0]
        p = price.position_of(monthly)
        self.assertEqual(p["n"], 4, "unchecked and one-off prices are left out")
        self.assertEqual((p["min"], p["median"], p["max"]), (400.0, 700.0, 1200.0))
        self.assertEqual((p["you"], p["cheaper_than"], p["dearer_than"]), (300.0, 4, 0))
        self.assertEqual(p["band"], "bottom quarter")
        self.assertIn("e", monthly["unknown"])
        self.assertIn("f", monthly["unknown"], "a price in another period is not comparable, so unknown here")

    def test_too_little_evidence(self):
        t = {"business": "x", "rows": [row("a", "audit", 100.0), row("you", "audit", 90.0)]}
        p = price.position_of(price.groups(t)[0])
        self.assertEqual(p["band"], "too little evidence")
        moves = price.suggest(p, None)
        self.assertTrue(moves[0][0].startswith("hold"))

    def test_moves_name_their_evidence(self):
        p = price.position_of([g for g in price.groups(table()) if g["period"] == "month"][0])
        moves = price.suggest(p, None)
        self.assertIn("raise coaching to $700 a month", moves[0][0])
        self.assertIn("4 of 4", moves[0][1])
        top = price.position_of([g for g in price.groups(table(you=2000.0)) if g["period"] == "month"][0])
        self.assertEqual(top["band"], "top quarter")
        self.assertTrue(price.suggest(top, None)[0][0].startswith("hold"))

    def test_floor_warns(self):
        p = price.position_of([g for g in price.groups(table()) if g["period"] == "month"][0])
        moves = price.suggest(p, 800.0)
        self.assertIn("loses money", moves[0][1])


class Margin(unittest.TestCase):
    def test_numbers_copy_runs(self):
        base = price.margin_line(price.run_numbers(NUMBERS, None))
        higher = price.margin_line(price.run_numbers(NUMBERS, 700))
        self.assertEqual(base["price"], 300.0)
        self.assertGreater(higher["leaves_per_sale"], base["leaves_per_sale"])


class Commands(unittest.TestCase):
    def test_position_moves_approve(self):
        tmp = tempfile.mkdtemp()
        old = os.environ.get(offerlib.LIBRARY_ENV)
        os.environ[offerlib.LIBRARY_ENV] = tmp
        try:
            run = offerlib.new_run("Acme")
            offerlib.write_json(os.path.join(run, "table.json"), table())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(price.main(["position", "--business", "Acme"]), 0)
                self.assertEqual(price.main(["moves", "--business", "Acme", "--numbers", NUMBERS]), 0)
                self.assertEqual(price.main(["approve", "2", "--business", "Acme"]), 0)
            moves = offerlib.read_json(os.path.join(run, "moves.json"))
            self.assertEqual([m["approved"] for m in moves], [False, True])
            self.assertIn("leaves_per_sale", moves[0]["at_that_price"])
            with open(os.path.join(run, "position.md")) as fh:
                self.assertIn("cheaper than 4", fh.read())
        finally:
            if old is None:
                os.environ.pop(offerlib.LIBRARY_ENV, None)
            else:
                os.environ[offerlib.LIBRARY_ENV] = old
            shutil.rmtree(tmp)


class SharedCopies(unittest.TestCase):
    def test_numbers_is_identical_to_startup_numbers(self):
        original = os.path.join(ROOT, "startup-numbers", "numbers.py")
        if not os.path.exists(original):
            self.skipTest("startup-numbers is not beside this skill")
        self.assertTrue(filecmp.cmp(original, os.path.join(SKILL, "scripts", "numbers.py"), shallow=False),
                        "scripts/numbers.py has drifted from startup-numbers/numbers.py")

    def test_offerlib_is_identical_in_every_skill(self):
        mine = os.path.join(SKILL, "scripts", "offerlib.py")
        for other in ("offer", "offer-build"):
            path = os.path.join(ROOT, other, "scripts", "offerlib.py")
            if os.path.exists(path):
                self.assertTrue(filecmp.cmp(mine, path, shallow=False), "%s has drifted" % path)


if __name__ == "__main__":
    unittest.main()
