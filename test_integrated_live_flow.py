from pathlib import Path
import unittest


class IntegratedLiveFlowSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent
        cls.learner = (root / "live_activity.html").read_text("utf-8")
        cls.host = (root / "live_host.html").read_text("utf-8")

    def test_every_learner_gets_required_prep_before_live_sync(self):
        for marker in (
            "function renderPreparation()", "Підготовка · 7–10 хвилин",
            "live_preparation_done", "prepDone&&next!==currentId",
            "step_ids", "lexicon.slice(0,3)",
        ):
            self.assertIn(marker, self.learner)

    def test_lesson_ends_in_private_first_video_and_optional_relay(self):
        for marker in (
            "function showVideoMission", "navigator.mediaDevices.getUserMedia",
            "Зберегти приватно", "Передати естафету", "live_video_done",
            "visibility:'private'", "duration_seconds:videoSec",
        ):
            self.assertIn(marker, self.learner)

    def test_host_has_exact_60_minute_integrated_plan(self):
        for marker in (
            'id="plan"', "function renderPlan()", "Похвилинний сценарій",
            "Граматика → мовлення → відео", "Фінальна відеомісія",
        ):
            self.assertIn(marker, self.host)


if __name__ == "__main__":
    unittest.main()
