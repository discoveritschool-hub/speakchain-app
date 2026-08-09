import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent


def embedded_apps(source: str) -> dict:
    marker = "const APPS   = "
    start = source.index(marker) + len(marker)
    decoder = json.JSONDecoder()
    apps, _ = decoder.raw_decode(source[start:])
    return apps


class ChainyContinuityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.buddy = (ROOT / "speaking_buddy.html").read_text(encoding="utf-8")
        cls.shell = (ROOT / "index_v2.html").read_text(encoding="utf-8")
        cls.embedded_buddy = embedded_apps(cls.shell)["s-buddy"]["js"]

    def test_daily_limit_is_restored_from_the_server(self):
        for source in (self.buddy, self.embedded_buddy):
            self.assertIn("/buddy_status", source)
            self.assertIn("msgCount = Math.max(0, Number(data.msg_count))", source)
            self.assertIn("msgCount = Math.max(0, maxMsgs - Number(data.remaining))", source)
            self.assertIn("dailyStatus?.history", source)
            self.assertIn("Продовжуємо сьогоднішню розмову", source)

    def test_reopening_chainy_reuses_the_active_transcript(self):
        for source in (self.buddy, self.embedded_buddy):
            self.assertIn("currentScenario?.isChainy", source)
            self.assertIn("history.some(item => item?.role === 'user'", source)
            self.assertIn("showScreen('s-chat')", source)

    def test_dictionary_closes_back_to_the_active_chainy_overlay(self):
        self.assertIn("activeOverlay?.id==='ov-buddy' && id==='ov-vocab'", self.shell)
        self.assertIn("if(wasVocab && BUDDY_TOOL_RETURN)", self.shell)
        self.assertIn("$('#ov-buddy')?.classList.add('on')", self.shell)


if __name__ == "__main__":
    unittest.main()
