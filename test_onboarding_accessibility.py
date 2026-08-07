"""Dependency-free behavioral coverage for the Day-1 onboarding module."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STANDALONE = ROOT / "day1_onboarding.html"
SHELL = ROOT / "index_v2.html"


def extract_apps(source: str) -> dict:
    marker = source.index("const APPS")
    start = source.index("{", source.index("=", marker))
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(source[start:index + 1])
    raise AssertionError("unterminated APPS object")


def parse_standalone() -> dict[str, str]:
    source = STANDALONE.read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", source, re.S)
    body = re.search(r"<body>(.*?)</body>", source, re.S)
    if not style or not body:
        raise AssertionError("standalone onboarding is missing style/body")
    body_source = body.group(1)
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", body_source, re.S)
    return {
        "css": style.group(1),
        "html": re.sub(r"<script[^>]*>.*?</script>", "", body_source, flags=re.S).strip(),
        "js": max(scripts, key=len),
    }


def node_binary() -> str:
    found = shutil.which("node")
    if found:
        return found
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    if bundled.exists():
        return str(bundled)
    raise unittest.SkipTest("Node is unavailable")


class OnboardingAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.standalone = parse_standalone()
        cls.embedded = extract_apps(SHELL.read_text(encoding="utf-8"))["ov-onboarding"]

    def test_sync_output_is_byte_equivalent(self):
        self.assertEqual(self.embedded, self.standalone)

    def test_standalone_and_embedded_javascript_parse(self):
        for source in (self.standalone["js"], self.embedded["js"]):
            result = subprocess.run(
                [node_binary(), "--check", "-"], input=source,
                text=True, encoding="utf-8", capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_button_activation_preserves_state_focus_and_progress(self):
        standalone_source = STANDALONE.read_text(encoding="utf-8")
        self.assertNotIn("user-scalable=no", standalone_source)
        self.assertIn(
            'id="doneScreen" role="status" aria-live="polite" tabindex="-1"',
            standalone_source,
        )
        harness = r"""
class Element {
  constructor(tagName='div', id='') {
    this.tagName=tagName.toUpperCase(); this.id=id; this.children=[];
    this.attributes={}; this.style={}; this.dataset={}; this.disabled=false;
    this.textContent=''; this.type=''; this.onclick=null; this._innerHTML='';
  }
  set innerHTML(value) {
    this._innerHTML=String(value); this.children=[];
    if (this.id==='body' && value.includes('id="onboarding-title"')) {
      document.elements['onboarding-title']=new Element('h1','onboarding-title');
    }
  }
  get innerHTML(){ return this._innerHTML; }
  setAttribute(name,value){ this.attributes[name]=String(value); }
  getAttribute(name){ return this.attributes[name]; }
  appendChild(child){ this.children.push(child); return child; }
  focus(){ document.activeElement=this; }
}
const document={elements:{},activeElement:null,
  getElementById(id){ return this.elements[id] || null; },
  createElement(tag){ return new Element(tag); }
};
for (const id of ['body','prog','onboarding-progress','hint','cta','backBtn','stepCount','stepStatus','screen','doneScreen','ctaBar']) {
  document.elements[id]=new Element('div',id);
}
document.elements.doneScreen.setAttribute('role','status');
document.elements.doneScreen.setAttribute('aria-live','polite');
const window={Telegram:null,scrollTo(){}};
const location={search:''};
const requestAnimationFrame=(callback)=>callback();
const fetch=()=>Promise.resolve();
const setTimeout=()=>0;
"""
        assertions = r"""
function assert(condition,message){ if(!condition) throw new Error(message); }
function choiceGroup(){
  return document.getElementById('body').children.find((child)=>
    child.getAttribute('role')==='group' || child.getAttribute('role')==='radiogroup');
}
let group=choiceGroup();
assert(group.getAttribute('role')==='group','choice container role');
assert(group.children[0].tagName==='BUTTON','native button');
assert(group.children[0].type==='button','non-submit button');
assert(group.children[0].getAttribute('aria-pressed')==='false','initial state');
assert(cta.disabled===true,'required CTA begins disabled');

// A native button dispatches the same click for pointer, Enter and Space.
group.children[0].onclick();
group=choiceGroup();
assert(answers.goal.join(',')==='travel','first keyboard selection');
assert(group.children[0].getAttribute('aria-pressed')==='true','announced selected state');
assert(document.activeElement===group.children[0],'focus survives render');
assert(cta.disabled===false,'CTA enabled after required selection');
group.children[1].onclick(); group=choiceGroup();
group.children[2].onclick(); group=choiceGroup();
group.children[3].onclick();
assert(answers.goal.length===3,'maximum selection remains enforced');

cta.onclick();
assert(idx===1,'next advances one screen');
assert(document.activeElement===document.getElementById('onboarding-title'),'heading receives focus');
assert(progressEl.getAttribute('aria-valuenow')==='2','progress updates');
assert(progressEl.getAttribute('aria-valuetext')==='Крок 2 з 7','progress is announced');
assert(stepStatus.textContent==='Крок 2 з 7','live progress status updates');
group=choiceGroup();
group.children[0].onclick(); group=choiceGroup();
group.children.at(-1).onclick(); group=choiceGroup();
assert(answers.tried.join(',')==='nothing','exclusive choice clears previous choices');
assert(document.activeElement===group.children.at(-1),'exclusive choice keeps focus');

backBtn.onclick();
assert(idx===0,'back returns one screen');
assert(document.activeElement===document.getElementById('onboarding-title'),'back focuses heading');

// Visit every remaining screen and keep the established multi-select behavior.
cta.onclick(); assert(idx===1,'revisits screen 2');
cta.onclick(); assert(idx===2,'advances to screen 3');
group=choiceGroup(); group.children[0].onclick(); cta.onclick();
assert(idx===3,'advances to screen 4');
group=choiceGroup(); group.children[0].onclick(); cta.onclick();
assert(idx===4,'advances to screen 5');
group=choiceGroup(); group.children[0].onclick(); cta.onclick();
assert(idx===5,'advances to screen 6');
group=choiceGroup(); group.children[0].onclick(); cta.onclick();
assert(idx===6,'advances to screen 7');

group=choiceGroup();
assert(group.getAttribute('role')==='radiogroup','single-select container is a radiogroup');
assert(group.children.every((choice)=>choice.getAttribute('role')==='radio'),'single choices are radios');
assert(group.children.every((choice)=>choice.getAttribute('aria-checked')==='false'),'radios begin unchecked');
assert(group.children.every((choice)=>choice.getAttribute('aria-pressed')===undefined),'radios do not expose toggle-button state');
group.children[0].onclick(); group=choiceGroup();
assert(answers.time==='5','first radio selection is stored');
assert(group.children[0].getAttribute('aria-checked')==='true','first radio is announced checked');
assert(document.activeElement===group.children[0],'radio focus survives render');
group.children[1].onclick(); group=choiceGroup();
assert(answers.time==='15','second radio replaces first selection');
assert(group.children[0].getAttribute('aria-checked')==='false','previous radio is unchecked');
assert(group.children[1].getAttribute('aria-checked')==='true','new radio is checked');
assert(cta.disabled===false,'finish CTA enabled after radio selection');

cta.onclick();
assert(document.getElementById('screen').style.display==='none','form screen is hidden after finish');
assert(document.getElementById('doneScreen').style.display==='block','done screen is shown');
assert(document.getElementById('ctaBar').style.display==='none','CTA bar is hidden after finish');
assert(document.activeElement===document.getElementById('doneScreen'),'done screen receives focus');
assert(document.getElementById('doneScreen').getAttribute('role')==='status','done screen remains a live status');
assert(document.getElementById('doneScreen').getAttribute('aria-live')==='polite','completion is announced politely');
"""
        result = subprocess.run(
            [node_binary(), "-"], input=harness + self.standalone["js"] + assertions,
            text=True, encoding="utf-8", capture_output=True, check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
