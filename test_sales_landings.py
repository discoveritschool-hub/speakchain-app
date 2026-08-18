from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).parent


class _Parser(HTMLParser):
    pass


class SalesLandingTests(unittest.TestCase):
    def test_landings_are_valid_and_have_one_purchase_route(self):
        expected = {
            "challenge_landing.html": "start=easy_english_challenge",
            "plans_landing.html": "start=plans_basic_6m",
        }
        for filename, route in expected.items():
            source = (ROOT / filename).read_text(encoding="utf-8")
            parser = _Parser()
            parser.feed(source)
            self.assertIn(route, source)
            self.assertIn("SpeakChain", source)
            self.assertNotIn("Chainy без обмежень", source)
            self.assertIn("attribution_token", source)

    def test_plan_ctas_preserve_product_and_period(self):
        source = (ROOT / "plans_landing.html").read_text(encoding="utf-8")
        self.assertIn("start=plans_basic_6m", source)
        self.assertIn("start=plans_premium_6m", source)
        self.assertIn("plans_${plan}_${selectedTerm", source)

    def test_plans_copy_keeps_live_communication_in_basic(self):
        source = (ROOT / "plans_landing.html").read_text(encoding="utf-8")
        self.assertIn("Живе спілкування з учасниками", source)
        self.assertIn("8 ефірів із блогером і викладачем", source)
        self.assertNotIn("персональ", source.lower())
        self.assertNotIn("наставниц", source.lower())

    def test_inline_scripts_parse(self):
        for filename in ("challenge_landing.html", "plans_landing.html"):
            source = (ROOT / filename).read_text(encoding="utf-8")
            scripts = re.findall(r"<script>(.*?)</script>", source, re.S)
            for script in scripts:
                result = subprocess.run(
                    ["node", "--check", "-"], input=script,
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
