(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.SpeakChainSeek = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const SEEK_SECONDS = 10;
  const DOUBLE_TAP_MS = 360;
  const SYNTHETIC_CLICK_DEDUP_MS = 700;
  const GESTURE_BOUNDS = Object.freeze({
    left: Object.freeze({left: 0, right: 30}),
    right: Object.freeze({left: 70, right: 100}),
    topPx: 64,
    bottomPx: 84,
  });

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function createSeekController(options) {
    const getPlayer = options && typeof options.getPlayer === 'function'
      ? options.getPlayer : function () { return null; };
    const isReady = options && typeof options.isReady === 'function'
      ? options.isReady : function () { return false; };
    const announce = options && typeof options.announce === 'function'
      ? options.announce : function () {};
    const now = options && typeof options.now === 'function'
      ? options.now : function () { return Date.now(); };
    let pendingTap = null;
    let lastTouchAt = null;

    function unavailable() {
      announce('unavailable');
      return {ok: false, reason: 'unavailable'};
    }

    function seekRelative(requestedDelta) {
      const numericDelta = Number(requestedDelta);
      const delta = clamp(Number.isFinite(numericDelta) ? numericDelta : 0, -SEEK_SECONDS, SEEK_SECONDS);
      const player = getPlayer();
      if (!isReady() || !player || !delta
          || typeof player.getCurrentTime !== 'function'
          || typeof player.getDuration !== 'function'
          || typeof player.seekTo !== 'function') return unavailable();
      try {
        const current = Number(player.getCurrentTime());
        const duration = Number(player.getDuration());
        if (!Number.isFinite(current) || !Number.isFinite(duration) || duration <= 0) return unavailable();
        const target = clamp(current + delta, 0, duration);
        player.seekTo(target, true);
        announce(delta < 0 ? 'backward' : 'forward');
        return {ok: true, target: target, delta: delta};
      } catch (_) {
        return unavailable();
      }
    }

    function handleGesture(direction, source, timestamp) {
      const at = Number.isFinite(Number(timestamp)) ? Number(timestamp) : now();
      if (direction !== 'left' && direction !== 'right') return {ok: false, reason: 'direction'};
      if (source === 'click' && lastTouchAt !== null) {
        const sinceTouch = at - lastTouchAt;
        if (sinceTouch >= 0 && sinceTouch <= SYNTHETIC_CLICK_DEDUP_MS) {
          return {ok: false, reason: 'synthetic-click'};
        }
      }
      if (source === 'touch') lastTouchAt = at;

      if (!pendingTap || pendingTap.direction !== direction
          || at < pendingTap.at || at - pendingTap.at > DOUBLE_TAP_MS) {
        pendingTap = {direction: direction, at: at};
        return {ok: false, reason: 'first-tap'};
      }
      pendingTap = null;
      return seekRelative(direction === 'left' ? -SEEK_SECONDS : SEEK_SECONDS);
    }

    function resetGestures() {
      pendingTap = null;
      lastTouchAt = null;
    }

    return {seekRelative: seekRelative, handleGesture: handleGesture, resetGestures: resetGestures};
  }

  function applyGestureBounds(layer) {
    if (!layer || typeof layer.querySelector !== 'function') return false;
    const left = layer.querySelector('[data-seek-direction="left"]');
    const right = layer.querySelector('[data-seek-direction="right"]');
    if (!left || !right) return false;
    [left, right].forEach(function (zone) {
      zone.style.top = GESTURE_BOUNDS.topPx + 'px';
      zone.style.bottom = GESTURE_BOUNDS.bottomPx + 'px';
    });
    left.style.left = GESTURE_BOUNDS.left.left + '%';
    left.style.right = (100 - GESTURE_BOUNDS.left.right) + '%';
    right.style.left = GESTURE_BOUNDS.right.left + '%';
    right.style.right = (100 - GESTURE_BOUNDS.right.right) + '%';
    return true;
  }

  function bindSeekControls(options) {
    const controller = options.controller;
    const now = typeof options.now === 'function' ? options.now : function () { return Date.now(); };
    const bindings = [];
    function on(target, eventName, handler, eventOptions) {
      if (!target || typeof target.addEventListener !== 'function') return;
      target.addEventListener(eventName, handler, eventOptions);
      bindings.push(function () { target.removeEventListener(eventName, handler, eventOptions); });
    }
    on(options.backButton, 'click', function () { controller.seekRelative(-SEEK_SECONDS); });
    on(options.forwardButton, 'click', function () { controller.seekRelative(SEEK_SECONDS); });
    on(options.keyboardTarget, 'keydown', function (event) {
      if (event.target !== options.keyboardTarget) return;
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      controller.seekRelative(event.key === 'ArrowLeft' ? -SEEK_SECONDS : SEEK_SECONDS);
    });
    function bindZone(zone, direction) {
      on(zone, 'touchend', function (event) {
        event.preventDefault();
        controller.handleGesture(direction, 'touch', now());
      }, {passive: false});
      on(zone, 'click', function (event) {
        event.preventDefault();
        controller.handleGesture(direction, 'click', now());
      });
    }
    bindZone(options.leftZone, 'left');
    bindZone(options.rightZone, 'right');
    return function unbind() { bindings.splice(0).forEach(function (remove) { remove(); }); };
  }

  return Object.freeze({
    SEEK_SECONDS: SEEK_SECONDS,
    DOUBLE_TAP_MS: DOUBLE_TAP_MS,
    SYNTHETIC_CLICK_DEDUP_MS: SYNTHETIC_CLICK_DEDUP_MS,
    GESTURE_BOUNDS: GESTURE_BOUNDS,
    createSeekController: createSeekController,
    applyGestureBounds: applyGestureBounds,
    bindSeekControls: bindSeekControls,
  });
});
