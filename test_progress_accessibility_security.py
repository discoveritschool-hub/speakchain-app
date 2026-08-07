"""Dependency-free security, keyboard and parity coverage for the progress module."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STANDALONE = ROOT / "progress.html"
SHELL = ROOT / "index_v2.html"
BASE = "05e4e555586b5cabbeeb168d137d0cb520eeccfd"


def extract_apps_span(source: str) -> tuple[int, int]:
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
                return start, index + 1
    raise AssertionError("unterminated APPS object")


def extract_apps(source: str) -> dict:
    start, end = extract_apps_span(source)
    return json.loads(source[start:end])


def parse_standalone() -> dict[str, str]:
    source = STANDALONE.read_text(encoding="utf-8")
    styles = re.findall(r"<style>(.*?)</style>", source, re.S)
    body = re.search(r"<body>(.*?)</body>", source, re.S)
    if len(styles) != 1 or not body:
        raise AssertionError("progress canonical must have exactly one style and one body")
    body_source = body.group(1)
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", body_source, re.S)
    return {
        "css": styles[0],
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


class ProgressSecurityAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = STANDALONE.read_text(encoding="utf-8")
        cls.standalone = parse_standalone()
        cls.apps = extract_apps(SHELL.read_text(encoding="utf-8"))

    def test_sync_is_exact_and_other_apps_are_unchanged(self):
        self.assertEqual(self.apps["s-prog"], self.standalone)
        result = subprocess.run(
            ["git", "show", f"{BASE}:index_v2.html"], cwd=ROOT,
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        before_source = result.stdout
        before = extract_apps(before_source)
        self.assertEqual(
            {key: value for key, value in self.apps.items() if key != "s-prog"},
            {key: value for key, value in before.items() if key != "s-prog"},
        )
        current_source = SHELL.read_text(encoding="utf-8")
        current_start, current_end = extract_apps_span(current_source)
        before_start, before_end = extract_apps_span(before_source)
        self.assertEqual(current_source[:current_start], before_source[:before_start])
        self.assertEqual(current_source[current_end:], before_source[before_end:])

    def test_static_security_and_accessibility_contract(self):
        self.assertNotIn("user-scalable=no", self.source)
        self.assertNotIn("maximum-scale", self.source)
        self.assertNotIn("innerHTML", self.standalone["js"])
        self.assertNotRegex(
            re.sub(r"<!--.*?-->", "", self.standalone["html"], flags=re.S),
            r"<[^>]+\sonclick=",
        )
        for marker in (
            'id="topic-modal" role="dialog" aria-modal="true"',
            'id="tabs" role="tablist"',
            'id="progress-status" role="status" aria-live="polite"',
            'role="progressbar"',
            'button.disabled = locked',
            'button.addEventListener("click"',
            'requestAnimationFrame(() => document.getElementById("modal-close-btn").focus())',
            'if(event.key === "Escape")',
            'requestAnimationFrame(() => opener?.focus?.())',
            'window.addEventListener(\'pagehide\', endSession)',
        ):
            self.assertIn(marker, self.source)

    def test_javascript_parses(self):
        for source in (self.standalone["js"], self.apps["s-prog"]["js"]):
            result = subprocess.run(
                [node_binary(), "--check", "-"], input=source,
                text=True, encoding="utf-8", capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_adversarial_payload_api_stt_keyboard_and_dialog_behavior(self):
        harness = r'''
class ClassList {
  constructor(owner){ this.owner=owner; }
  values(){ return this.owner.className.split(/\s+/).filter(Boolean); }
  contains(value){ return this.values().includes(value); }
  add(...values){ this.owner.className=[...new Set([...this.values(),...values])].join(' '); }
  remove(...values){ this.owner.className=this.values().filter(value=>!values.includes(value)).join(' '); }
  toggle(value,force){ const on=force===undefined?!this.contains(value):Boolean(force); on?this.add(value):this.remove(value); return on; }
}
class Element {
  constructor(tag='div',id=''){
    this.tagName=tag.toUpperCase(); this._id=''; this.className=''; this.classList=new ClassList(this);
    this.children=[]; this.parentNode=null; this.attributes={}; this.listeners={}; this.style={};
    this.hidden=false; this.disabled=false; this.tabIndex=0; this._text=''; this.scrollWidth=300; this.clientWidth=120; this.scrollLeft=0;
    if(id) this.id=id;
  }
  set id(value){ this._id=String(value); if(this._id) document.elements[this._id]=this; }
  get id(){ return this._id; }
  set textContent(value){ this._text=String(value??''); this.children=[]; }
  get textContent(){ return this._text+this.children.map(child=>child.textContent||'').join(''); }
  setAttribute(name,value){ this.attributes[name]=String(value); if(name==='id')this.id=value; }
  getAttribute(name){ return this.attributes[name]; }
  appendChild(child){ if(typeof child==='string')child=new TextNode(child); child.parentNode=this; this.children.push(child); return child; }
  append(...children){ children.forEach(child=>this.appendChild(child)); }
  replaceChildren(...children){ this.children=[]; this._text=''; this.append(...children); }
  replaceWith(next){ if(!this.parentNode)return; const i=this.parentNode.children.indexOf(this); if(i>=0){next.parentNode=this.parentNode;this.parentNode.children[i]=next;} }
  addEventListener(type,callback){ (this.listeners[type]??=[]).push(callback); }
  dispatchEvent(event){ event.target??=this; event.currentTarget=this; (this.listeners[event.type]||[]).forEach(callback=>callback(event)); }
  click(){ if(!this.disabled)this.dispatchEvent({type:'click',preventDefault(){}}); }
  focus(){ if(!this.disabled)document.activeElement=this; }
  querySelectorAll(selector){
    const all=[]; const walk=node=>{ for(const child of node.children){all.push(child);walk(child);} }; walk(this);
    if(selector==='button:not(:disabled)')return all.filter(node=>node.tagName==='BUTTON'&&!node.disabled);
    if(selector.includes('button:not(:disabled)'))return all.filter(node=>node.tagName==='BUTTON'&&!node.disabled);
    if(selector.startsWith('.'))return all.filter(node=>node.classList.contains(selector.slice(1)));
    return all;
  }
  querySelector(selector){ return this.querySelectorAll(selector)[0]||null; }
  scrollBy(options){ this.scrollLeft+=Number(options?.left||0); }
  scrollTo(){} scrollIntoView(){}
}
class TextNode { constructor(text){this.tagName='#TEXT';this._text=String(text);this.children=[];this.parentNode=null;} get textContent(){return this._text;} }
const document={elements:{},activeElement:null,visibilityState:'visible',listeners:{},
  createElement(tag){return new Element(tag);}, createTextNode(text){return new TextNode(text);},
  getElementById(id){return this.elements[id]||null;},
  querySelector(selector){ if(selector.startsWith('.'))return Object.values(this.elements).find(node=>node.classList?.contains(selector.slice(1)))||null; return null; },
  querySelectorAll(){return[];}, addEventListener(type,callback){(this.listeners[type]??=[]).push(callback);}
};
const ids=['hdr-name','hdr-level','overall-fill','overall-left','overall-right','overall-progress','journey-pct','journey-fill','journey-progress','journey-marks','streak-strip','streak-val','streak-best','tabs','tabs-scroll-hint','stats-row','first-day-banner','lvl-progress','vocab-progress','next-topic-card','topics-list','progress-status','diagnostic-btn','progress-close-btn','topic-modal','modal-title','modal-body','modal-close-btn'];
ids.forEach(id=>new Element(id.includes('btn')||id==='tabs-scroll-hint'?'button':'div',id));
document.elements['topic-modal'].setAttribute('role','dialog'); document.elements['topic-modal'].setAttribute('aria-modal','true'); document.elements['topic-modal'].hidden=true;
const attack='<img src=x onerror=globalThis.pwned=1>';
const topic='Topic '+attack+"');globalThis.pwned=2;//";
const payload={name:'Student '+attack,levels:['A1','A2'],level:'A1',level_names:{A1:'Level '+attack},cefr_grammar:{A1:[topic],A2:['Future']},topics_data:{},scores:[70],done_lessons:1,vocab_coverage:{A1:{known:attack,target:10,pct:999,gap:2}},vocab_volume:{A1:12}};
payload.topics_data[topic]={mastery:999,color:'url(x)',buddy_errors:1,buddy_examples:[{phrase:attack,correction:'safe '+attack,explanation:attack,date:attack}],steps_done:{video:false,table:false,exercises:false,buddy:false}};
const location={search:'?d='+encodeURIComponent(JSON.stringify(payload))};
class SpeechRecognition { start(){this.onresult?.({results:[[{transcript:'heard '+attack}]]});} stop(){} }
const Telegram={WebApp:{ready(){},expand(){},initDataUnsafe:{user:{id:7}},initData:'signed',sendData(){},close(){}}};
const window={Telegram,SC_BOT_API:'https://example.test',location,SpeechRecognition,speechSynthesis:{cancel(){},speak(){},getVoices(){return[];}},showReward:null,addEventListener(){},scrollTo(){}};
const navigator={mediaDevices:{getUserMedia:async()=>({getTracks:()=>[]})},sendBeacon(){return true;}};
const speechSynthesis=window.speechSynthesis;
const SpeechSynthesisUtterance=function(text){this.text=text;};
const requestAnimationFrame=callback=>callback();
const setTimeout=callback=>{callback();return 1;};
let fetch=async url=>({ok:true,json:async()=>({})});
const Blob=function(){}; const Audio=function(){this.play=()=>{}}; const URL={createObjectURL(){return'blob:test';}};
'''
        assertions = r'''
function assert(condition,message){if(!condition)throw new Error(message);}
function descendants(root){const result=[];const walk=node=>{for(const child of node.children||[]){result.push(child);walk(child);}};walk(root);return result;}
(async()=>{
  assert(document.getElementById('hdr-name').textContent.includes(attack),'name remains literal text');
  assert(document.getElementById('overall-progress').getAttribute('aria-valuenow')==='50','clamped topic mastery produces bounded overall progress');
  const tabs=document.getElementById('tabs').children;
  assert(tabs.every(tab=>tab.tagName==='BUTTON'),'level tabs are native buttons');
  assert(tabs[1].disabled===true,'future level is actually disabled');
  tabs[1].click(); assert(activeLevel==='A1','disabled level cannot activate');
  const topicButton=document.getElementById('topics-list').children[0];
  assert(topicButton.tagName==='BUTTON','topic is a native button');
  assert(topicButton.textContent.includes(attack),'topic remains literal text');
  topicButton.focus(); topicButton.click();
  const modal=document.getElementById('topic-modal');
  assert(modal.hidden===false&&modal.classList.contains('active'),'dialog opens');
  assert(document.activeElement===document.getElementById('modal-close-btn'),'dialog close receives focus');
  const steps=descendants(document.getElementById('modal-body')).filter(node=>node.classList?.contains('step'));
  assert(steps.length===4&&steps.every(step=>step.tagName==='BUTTON'),'workflow uses native buttons');
  assert(steps.slice(1).every(step=>step.disabled),'future workflow steps are disabled');
  assert(document.getElementById('modal-body').textContent.includes(attack),'buddy fields remain literal text');
  modal.dispatchEvent({type:'keydown',key:'Escape',preventDefault(){}});
  assert(modal.hidden===true,'Escape closes dialog');
  assert(document.activeElement===topicButton,'dialog restores opener focus');

  openTopic(topic,topicButton);
  fetch=async url=>({ok:true,json:async()=>url.includes('topic_table')?{found:true,ua:attack,signals:[attack],table:[[attack,attack,attack]],formula:attack}: {}});
  await openTopicTable(topic);
  assert(document.getElementById('topic-table-panel').textContent.includes(attack),'API table remains literal text');
  assert(!descendants(document.getElementById('topic-table-panel')).some(node=>node.tagName==='SCRIPT'),'API cannot create script nodes');

  exSentences=['sentence '+attack]; exIdx=0; exSpoken=0;
  let panel=make('div','exercises-panel show'); panel.id='exercises-panel'; document.getElementById('modal-body').appendChild(panel);
  renderExercise();
  assert(document.getElementById('ex-sentence').textContent.includes(attack),'exercise remains literal text');
  await exToggleRecord();
  assert(document.getElementById('ex-sentence').textContent.includes('heard '+attack),'STT remains literal text');
  assert(globalThis.pwned===undefined,'no adversarial code executed');
  const suspicious=Object.values(document.elements).flatMap(descendants).filter(node=>['SCRIPT','SVG','IFRAME'].includes(node.tagName));
  assert(suspicious.length===0,'no executable nodes created');
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
'''
        result = subprocess.run(
            [node_binary(), "-"], input=harness + self.standalone["js"] + assertions,
            text=True, encoding="utf-8", capture_output=True, check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
