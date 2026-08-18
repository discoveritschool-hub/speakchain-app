from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "index_v2.html").read_text(encoding="utf-8")


class LiveBroadcastSurfaceTests(unittest.TestCase):
    def test_banner_is_global_not_nested_in_a_screen(self):
        banner = SOURCE.index('id="global-live-banner"')
        scroll = SOURCE.index('<div class="scroll">')
        first_screen = SOURCE.index('id="s-home"')
        self.assertLess(banner, scroll)
        self.assertLess(banner, first_screen)

    def test_payload_updates_banner_and_actions_are_gated(self):
        self.assertIn("syncGlobalLiveBroadcast(payload.d.live_broadcast)", SOURCE)
        self.assertIn("function openLiveBroadcast()", SOURCE)
        self.assertIn("L.join_url?'Приєднатися до ефіру'", SOURCE)
        self.assertIn("L.has_access?'none':'block'", SOURCE)


if __name__ == "__main__":
    unittest.main()
