from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ChainyCanonicalAssetTests(unittest.TestCase):
    def test_canonical_and_week_one_v2_assets_are_present(self):
        assets = [
            "assets/chainy/canonical/chainy-fullbody-v2.png",
            "assets/chainy/canonical/chainy-concept-v2.png",
            "assets/chainy/week-1/morning-routine-v2.png",
            "assets/chainy/week-1/english-practice-v2.png",
            "assets/chainy/week-1/more-time-v2.png",
            "assets/chainy/week-1/video-relay-v2.png",
        ]
        for relative_path in assets:
            path = ROOT / relative_path
            with self.subTest(asset=relative_path):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
