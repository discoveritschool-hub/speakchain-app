from __future__ import annotations

import re
import unittest
from pathlib import Path


PLAYER = Path(__file__).with_name("player.html")
VOCAB = Path(__file__).with_name("vocab.html")
SHELL = Path(__file__).with_name("index_v2.html")


class PlayerLearningFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PLAYER.read_text(encoding="utf-8")
        cls.shell = SHELL.read_text(encoding="utf-8")

    def test_hold_to_record_cycle_uses_one_compact_primary_button(self):
        self.assertIn('id="record-btn" aria-label="Утримуй, щоб записати себе">🎙</button>', self.source)
        self.assertIn('id="play-my" disabled hidden aria-hidden="true"', self.source)
        self.assertIn('.practice-actions #play-my { display:none!important; }', self.source)
        self.assertIn("recordBtn.addEventListener('pointerdown'", self.source)
        self.assertIn("recordBtn.addEventListener('pointerup'", self.source)
        self.assertIn("recordHoldTimer=setTimeout(()=>beginHeldRecording(true),320)", self.source)
        self.assertIn("if(!recordHoldStarted&&audioURL)toggleOwnPlayback()", self.source)
        self.assertIn("phraseCycle.recorded=true;phraseCycle.listened=false", self.source)
        self.assertIn("phraseCycle.listened=true;updateCycleStatus()", self.source)
        record_button_states = re.findall(r"recordBtn\.className\s*=\s*['\"]([^'\"]+)", self.source)
        self.assertTrue(record_button_states)
        self.assertTrue(all("hold-record" in state for state in record_button_states))
        self.assertNotIn('id="voice-retake"', self.source)
        self.assertIn("if (recSec>=15) stopRec()", self.source)
        self.assertNotIn('id="speak-with-chainy"', self.source)

    def test_level_scale_is_absent_and_chainy_is_offered_only_after_completion(self):
        self.assertNotIn('id="journey-strip"', self.source)
        self.assertNotIn('Ціль: C2', self.source)
        self.assertIn("if (e.data === YT.PlayerState.ENDED) notifyVideoCompleted()", self.source)
        self.assertIn("type:'speakchain-video-completed'", self.source)
        self.assertIn("if(wasPlayer && PLAYER_VIDEO_COMPLETED) offerSpeak()", self.shell)
        self.assertIn("if(event.data?.type==='speakchain-video-completed')", self.shell)
        self.assertNotIn("window.parent.postMessage(conversationBrief", self.source)

    def test_phrase_toolbar_is_compact_and_has_no_manual_navigation(self):
        self.assertNotIn("setCaptionStatus(`${fmt(", self.source)
        self.assertIn('id="phrase-original" aria-label="Прослухати оригінальну фразу">▶</button>', self.source)
        self.assertIn('id="phrase-save" aria-label="Зберегти фразу у словник">＋</button>', self.source)
        self.assertIn('id="vocab-drawer-open" aria-label="Відкрити мій словник">📖', self.source)
        self.assertIn('id="cycle-original">Оригінал ○</span>', self.source)
        self.assertIn('id="cycle-recorded">Запис ○</span>', self.source)
        self.assertIn('id="cycle-listened">Прослухано ○</span>', self.source)
        self.assertNotIn('id="phrase-prev"', self.source)
        self.assertNotIn('id="phrase-next"', self.source)
        self.assertNotIn('id="phrase-repeat"', self.source)
        self.assertIn("#session-bar {\n      background:var(--bg-card); padding:8px 16px;\n      display:none", self.source)
        self.assertIn(".playback-times {\n      display:none", self.source)

    def test_inline_user_dictionary_filters_words_and_phrases(self):
        self.assertIn('id="vocab-tab-video"', self.source)
        self.assertIn('id="vocab-tab-all"', self.source)
        self.assertIn("fetch(`${apiBase}/vocab_data`", self.source)
        self.assertIn("const groups=[['Слова'", self.source)
        self.assertIn("['Фрази'", self.source)
        self.assertIn("sessionSavedPhrases.includes(phrase)", self.source)

    def test_partner_captions_and_bounded_local_cache_are_supported(self):
        self.assertIn("playerData.caption_events||playerData.captions?.events", self.source)
        self.assertIn("const CAPTION_CACHE_TTL=7*24*60*60*1000", self.source)
        self.assertIn("for(const oldId of ids.slice(6))", self.source)
        self.assertIn("function normalizeCaptionEvents(events)", self.source)
        self.assertIn("function captionAt(seconds)", self.source)
        self.assertIn('id="interactive-transcript" aria-live="polite" hidden', self.source)
        self.assertIn("data.status==='processing'", self.source)
        self.assertIn("scheduleCaptionPoll()", self.source)
        self.assertIn("interactiveTranscript.hidden=true", self.source)
        self.assertNotIn("Відео працює без затримки", self.source)

    def test_subtitle_words_and_phrases_remain_clickable_and_saveable(self):
        self.assertIn("String(text).match(/[A-Za-z][A-Za-z'-]*/g)||[]", self.source)
        self.assertIn("await inspectCaptionWord(part.toLowerCase(), text)", self.source)
        self.assertIn("el.dataset.captionText=String(text)", self.source)
        self.assertIn("el.dataset.captionText!==found.text", self.source)
        self.assertIn("phraseSaveBtn.addEventListener('click',saveActivePhraseFromToolbar)", self.source)
        self.assertIn("action:'save_phrase'", self.source)
        self.assertIn("Збережено у словник з озвученням", self.source)
        vocab = VOCAB.read_text(encoding="utf-8")
        self.assertIn("function speakTTS(phrase)", vocab)
        self.assertIn("new SpeechSynthesisUtterance(phrase)", vocab)


if __name__ == "__main__":
    unittest.main()
