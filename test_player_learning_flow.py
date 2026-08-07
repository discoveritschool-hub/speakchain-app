from __future__ import annotations

import re
import unittest
from pathlib import Path


PLAYER = Path(__file__).with_name("player.html")
VOCAB = Path(__file__).with_name("vocab.html")


class PlayerLearningFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PLAYER.read_text(encoding="utf-8")

    def test_speechling_style_recording_cycle_uses_one_visible_primary_button(self):
        self.assertIn('id="record-btn">🎙 Записати себе</button>', self.source)
        self.assertIn('id="play-my" disabled hidden aria-hidden="true"', self.source)
        self.assertIn("toggleOwnPlayback(true)", self.source)
        self.assertIn('recordBtn.textContent="▶ Почути себе ще раз"', self.source)
        self.assertIn('id="voice-retake">↻ Записати ще раз</button>', self.source)
        self.assertIn("if (recSec>=15) stopRec()", self.source)

    def test_player_has_no_visible_original_or_timecode_controls(self):
        visible_original = re.findall(r">[^<]*Оригінал[^<]*<", self.source)
        self.assertEqual([], visible_original)
        self.assertNotIn("setCaptionStatus(`${fmt(", self.source)
        self.assertIn('id="phrase-repeat">🔁 Повторити фразу</button>', self.source)
        self.assertIn("#session-bar {\n      background:var(--bg-card); padding:8px 16px;\n      display:none", self.source)
        self.assertIn(".playback-times {\n      display:none", self.source)

    def test_partner_captions_and_bounded_local_cache_are_supported(self):
        self.assertIn("playerData.caption_events||playerData.captions?.events", self.source)
        self.assertIn("const CAPTION_CACHE_TTL=7*24*60*60*1000", self.source)
        self.assertIn("for(const oldId of ids.slice(6))", self.source)
        self.assertIn("function normalizeCaptionEvents(events)", self.source)
        self.assertIn("function captionAt(seconds)", self.source)

    def test_subtitle_words_and_phrases_remain_clickable_and_saveable(self):
        self.assertIn("await inspectCaptionWord(part.toLowerCase(), text)", self.source)
        self.assertIn("inspectCaptionPhrase(activeCaption.text)", self.source)
        self.assertIn("action:'save_phrase'", self.source)
        self.assertIn("Збережено у словник з озвученням", self.source)
        vocab = VOCAB.read_text(encoding="utf-8")
        self.assertIn("function speakTTS(phrase)", vocab)
        self.assertIn("new SpeechSynthesisUtterance(phrase)", vocab)


if __name__ == "__main__":
    unittest.main()
