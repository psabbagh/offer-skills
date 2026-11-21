"""The repo as a whole: three skills in the shape the plugin hosts load, nothing private in them,
the shared files identical, and the manifests pointing at them. Run from the repo root:
python3 -m unittest discover -s tests"""
import filecmp
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ["offer", "offer-price", "offer-build"]
PRIVATE = re.compile(r"pierre|/Users/|content-hub|ownhealth|roof\.ai|obsidian|repos/hq|op://|"
                     r"1password|claude-501|champmack|sakas", re.I)


class Skills(unittest.TestCase):
    def test_exactly_the_three_skills(self):
        self.assertEqual(sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir()), sorted(SKILLS))

    def test_each_skill_has_frontmatter_and_openai_yaml(self):
        for name in SKILLS:
            d = ROOT / "skills" / name
            text = (d / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\nname: %s\n" % name), name)
            self.assertIn("\ndescription: ", text.split("\n---", 2)[0], name)
            self.assertIn("$" + name, (d / "agents" / "openai.yaml").read_text(encoding="utf-8"), name)

    def test_nothing_private_in_the_repo(self):
        for p in list((ROOT / "skills").rglob("*")) + [ROOT / "README.md"] + list(ROOT.glob(".*-plugin/*.json")):
            if p.is_file() and "__pycache__" not in p.parts:
                for line in p.read_text(encoding="utf-8").splitlines():
                    self.assertIsNone(PRIVATE.search(line), "%s: %s" % (p.relative_to(ROOT), line.strip()))

    def test_shared_library_is_identical(self):
        first = ROOT / "skills" / "offer" / "scripts" / "offerlib.py"
        for name in SKILLS[1:]:
            self.assertTrue(filecmp.cmp(first, ROOT / "skills" / name / "scripts" / "offerlib.py", shallow=False), name)

    def test_each_skill_suite_passes(self):
        for name in SKILLS:
            out = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s",
                                  str(ROOT / "skills" / name / "tests")], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, name + "\n" + out.stderr[-2000:])

    def test_no_dash_characters_in_reader_facing_docs(self):
        for p in [ROOT / "README.md"] + [ROOT / "skills" / n / "SKILL.md" for n in SKILLS]:
            self.assertNotIn("—", p.read_text(encoding="utf-8"), p.name)


class Manifests(unittest.TestCase):
    def load(self, rel):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_claude_and_codex_agree(self):
        claude = self.load(".claude-plugin/plugin.json")
        codex = self.load(".codex-plugin/plugin.json")
        self.assertEqual(claude["name"], "offer-skills")
        for k in ("name", "version", "description", "license", "repository"):
            self.assertEqual(claude[k], codex[k], k)
        self.assertEqual(codex["skills"], "./skills/")

    def test_marketplaces_point_at_this_plugin(self):
        cm = self.load(".claude-plugin/marketplace.json")
        self.assertEqual([(p["name"], p["source"]) for p in cm["plugins"]], [("offer-skills", "./")])
        am = self.load(".agents/plugins/marketplace.json")
        self.assertEqual([(p["name"], p["source"]["path"]) for p in am["plugins"]], [("offer-skills", "./")])

    def test_readme_install_commands_match_the_manifests(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for cmd in ("claude plugin marketplace add psabbagh/offer-skills",
                    "claude plugin install offer-skills@offer-skills",
                    "codex plugin marketplace add psabbagh/offer-skills",
                    "codex plugin add offer-skills@offer-skills"):
            self.assertIn(cmd, readme)
        self.assertIn("not made, reviewed or endorsed by", readme)


if __name__ == "__main__":
    unittest.main()
