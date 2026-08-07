'use strict';

const assert = require('node:assert/strict');
const seek = require('./player_seek.js');

function fakeElement() {
  const listeners = new Map();
  return {
    style: {},
    addEventListener(name, handler) { listeners.set(name, handler); },
    removeEventListener(name, handler) { if (listeners.get(name) === handler) listeners.delete(name); },
    emit(name, values = {}) {
      const event = Object.assign({target: this, key: '', preventDefault() { this.defaultPrevented = true; }}, values);
      const handler = listeners.get(name);
      if (handler) handler(event);
      return event;
    },
  };
}

function fixture(initial = 50, duration = 100, ready = true) {
  let current = initial;
  const calls = [];
  const announcements = [];
  const player = {
    getCurrentTime: () => current,
    getDuration: () => duration,
    seekTo(target, allowSeekAhead) { calls.push([target, allowSeekAhead]); current = target; },
  };
  const controller = seek.createSeekController({
    getPlayer: () => player,
    isReady: () => ready,
    announce: code => announcements.push(code),
  });
  return {controller, player, calls, announcements, setReady(value) { ready = value; }};
}

{
  const f = fixture();
  assert.equal(f.controller.seekRelative(-10).target, 40);
  assert.equal(f.controller.seekRelative(10).target, 50);
  assert.deepEqual(f.calls, [[40, true], [50, true]], 'both directions use allowSeekAhead');
  assert.deepEqual(f.announcements, ['backward', 'forward']);
}

{
  const low = fixture(3, 100);
  const high = fixture(97, 100);
  assert.equal(low.controller.seekRelative(-10).target, 0, 'rewind clamps at zero');
  assert.equal(high.controller.seekRelative(10).target, 100, 'forward clamps at duration');
}

{
  const f = fixture(20, 100, false);
  assert.equal(f.controller.seekRelative(10).reason, 'unavailable');
  assert.equal(f.calls.length, 0);
  f.setReady(true);
  f.player.getDuration = () => Number.NaN;
  assert.equal(f.controller.seekRelative(-10).reason, 'unavailable');
  assert.deepEqual(f.announcements, ['unavailable', 'unavailable']);
}

{
  const f = fixture();
  assert.equal(f.controller.handleGesture('left', 'click', 0).reason, 'first-tap');
  assert.equal(f.calls.length, 0, 'first tap cannot seek');
  assert.equal(f.controller.handleGesture('left', 'click', 361).reason, 'first-tap');
  assert.equal(f.calls.length, 0, 'expired second tap cannot seek');
  assert.equal(f.controller.handleGesture('right', 'click', 500).reason, 'first-tap');
  assert.equal(f.calls.length, 0, 'opposite tap cannot seek');
  assert.equal(f.controller.handleGesture('right', 'click', 800).ok, true);
  assert.deepEqual(f.calls, [[60, true]], 'only a same-side in-window pair seeks');
}

{
  const f = fixture();
  assert.equal(f.controller.handleGesture('left', 'touch', 1000).reason, 'first-tap');
  assert.equal(f.controller.handleGesture('left', 'click', 1010).reason, 'synthetic-click');
  assert.equal(f.controller.handleGesture('left', 'touch', 1200).ok, true);
  assert.equal(f.controller.handleGesture('left', 'click', 1210).reason, 'synthetic-click');
  assert.deepEqual(f.calls, [[40, true]], 'synthetic clicks do not create extra seeks');
}

{
  const f = fixture();
  const back = fakeElement();
  const forward = fakeElement();
  const keyboard = fakeElement();
  const left = fakeElement();
  const right = fakeElement();
  let time = 2000;
  seek.bindSeekControls({controller: f.controller, backButton: back, forwardButton: forward,
    keyboardTarget: keyboard, leftZone: left, rightZone: right, now: () => time});
  back.emit('click');
  forward.emit('click');
  const keyEvent = keyboard.emit('keydown', {key: 'ArrowLeft'});
  assert.equal(keyEvent.defaultPrevented, true);
  assert.deepEqual(f.calls, [[40, true], [50, true], [40, true]],
    'native buttons and keyboard reuse the bounded seek helper');
  left.emit('touchend');
  time += 200;
  left.emit('touchend');
  assert.deepEqual(f.calls.at(-1), [30, true], 'bound gesture controller uses the same helper');
}

{
  const left = fakeElement();
  const right = fakeElement();
  const layer = {querySelector(selector) { return selector.includes('left') ? left : right; }};
  assert.equal(seek.applyGestureBounds(layer), true);
  const bounds = seek.GESTURE_BOUNDS;
  assert.ok(bounds.left.right <= bounds.right.left, 'gesture regions never overlap');
  assert.ok(bounds.right.left - bounds.left.right >= 40, 'at least 40% of center stays interactive');
  assert.ok(bounds.topPx >= 56, 'top player toggle remains outside gesture hit zones');
  assert.ok(bounds.bottomPx >= 64, 'native player controls remain outside gesture hit zones');
  assert.equal(left.style.right, '70%');
  assert.equal(right.style.left, '70%');
}

console.log('player seek behavior: 7/7 passed');
