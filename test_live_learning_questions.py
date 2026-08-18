from pathlib import Path
import unittest


class LiveLearningQuestionSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent
        cls.learner = (root / "live_activity.html").read_text(encoding="utf-8")
        cls.host = (root / "live_host.html").read_text(encoding="utf-8")

    def test_learner_can_ask_vote_and_read_answers(self):
        for marker in (
            'id="askOpen"', 'id="qaInput"', 'function askQuestion()',
            '/questions/${id}/vote', 'instant_help', 'Питання потоку',
        ):
            self.assertIn(marker, self.learner)

    def test_host_can_put_question_on_air_and_answer_it(self):
        for marker in (
            'id="questions"', 'function renderQuestions()',
            'data-air=', 'data-answer=', "updateQuestion(id,'answered'",
            'Q&A потоку',
        ):
            self.assertIn(marker, self.host)


if __name__ == "__main__":
    unittest.main()
