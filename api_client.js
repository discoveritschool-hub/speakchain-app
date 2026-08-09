(function (global) {
  'use strict';

  const PWA_ACCESS_KEY = 'speakchain.pwa.access.v1';
  const MUTATION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{15,63}$/;
  const generations = new Map();

  class ApiError extends Error {
    constructor(kind, message, details) {
      super(message || kind);
      this.name = 'ApiError';
      this.kind = kind;
      Object.assign(this, details || {});
    }
  }

  function timeoutMs(value) {
    const override = Number(global.__SC_API_TIMEOUT_MS);
    const candidate = Number.isFinite(override) ? override : Number(value);
    return Math.max(250, Math.min(15000, candidate || 6000));
  }

  async function auth() {
    const initData = global.Telegram?.WebApp?.initData;
    if (typeof initData === 'string' && initData) return { init_data: initData };
    if (global.SC_PWA?.ready) {
      try { await global.SC_PWA.ready; } catch (_) {}
    }
    try {
      const token = global.localStorage?.getItem(PWA_ACCESS_KEY);
      if (typeof token === 'string' && token.length > 0 && token.length <= 8192) {
        return { pwa_access_token: token };
      }
    } catch (_) {}
    return null;
  }

  function classify(response, payload) {
    const status = Number(response?.status || 0);
    const code = typeof payload?.error === 'string' ? payload.error : '';
    if (status === 401 || status === 403) return 'auth';
    if (status === 409) return 'conflict';
    if (status === 400 || status === 404 || status === 422) return 'validation';
    if (status === 429) return 'rate_limit';
    if (status >= 500) return 'server';
    if (!status) return 'network';
    return code ? 'server' : 'invalid_response';
  }

  function beginGeneration(scope) {
    const next = (generations.get(scope) || 0) + 1;
    generations.set(scope, next);
    return next;
  }

  function isCurrent(scope, generation) {
    return generations.get(scope) === generation;
  }

  function abortableDelay(ms, signal) {
    if (signal?.aborted) return Promise.reject(new ApiError('cancelled', 'Request cancelled'));
    return new Promise((resolve, reject) => {
      let timer;
      const onAbort = () => {
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
        reject(new ApiError('cancelled', 'Request cancelled'));
      };
      timer = setTimeout(() => {
        signal?.removeEventListener('abort', onAbort);
        if (signal?.aborted) onAbort();
        else resolve();
      }, ms);
      signal?.addEventListener('abort', onAbort, { once: true });
    });
  }

  async function request(path, options) {
    const opts = options || {};
    if (opts.signal?.aborted) throw new ApiError('cancelled', 'Request cancelled');
    const credentials = await auth();
    if (opts.signal?.aborted) throw new ApiError('cancelled', 'Request cancelled');
    if (!credentials) throw new ApiError('auth', 'Authentication required');
    const operation = opts.operation || 'read';
    const requestedAttempts = Math.max(1, Math.min(2, Number(opts.attempts) || 1));
    const body = Object.assign({}, opts.body || {});
    delete body.uid;
    delete body.init_data;
    delete body.pwa_access_token;
    let stableMutation = false;
    if (operation === 'mutation' && opts.mutationId != null) {
      if (typeof opts.mutationId !== 'string' || !MUTATION_ID_RE.test(opts.mutationId)) {
        throw new ApiError('invalid_request', 'Invalid mutation ID');
      }
      if (body.mutation_id != null && body.mutation_id !== opts.mutationId) {
        throw new ApiError('invalid_request', 'Mutation ID mismatch');
      }
      body.mutation_id = opts.mutationId;
      stableMutation = true;
    }
    const retryable = operation === 'read' || operation === 'idempotent' || stableMutation;
    const attempts = retryable ? requestedAttempts : 1;
    let lastError;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (opts.signal?.aborted) throw new ApiError('cancelled', 'Request cancelled');
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs(opts.timeout));
      const onAbort = () => controller.abort();
      opts.signal?.addEventListener('abort', onAbort, { once: true });
      try {
        const authenticatedBody = Object.assign({}, body, credentials);
        const response = await fetch(String(opts.base || '') + path, {
          method: opts.method || 'POST',
          headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
          body: JSON.stringify(authenticatedBody),
          signal: controller.signal
        });
        if (opts.signal?.aborted) throw new ApiError('cancelled', 'Request cancelled');
        if (controller.signal.aborted) throw new ApiError('timeout', 'Request timed out');
        const payload = await response.json().catch(() => ({}));
        if (opts.signal?.aborted) throw new ApiError('cancelled', 'Request cancelled');
        if (controller.signal.aborted) throw new ApiError('timeout', 'Request timed out');
        const accepted = Array.isArray(opts.acceptStatuses) && opts.acceptStatuses.includes(response.status);
        if (!response.ok && !accepted) {
          throw new ApiError(classify(response, payload), payload?.error || 'Request failed', {
            status: response.status, response, payload
          });
        }
        return { response, payload };
      } catch (error) {
        if (error instanceof ApiError) lastError = error;
        else if (error?.name === 'AbortError') {
          lastError = new ApiError(opts.signal?.aborted ? 'cancelled' : 'timeout', 'Request timed out', { cause: error });
        } else {
          lastError = new ApiError(global.navigator?.onLine === false ? 'offline' : 'network', 'Network unavailable', { cause: error });
        }
        const transient = ['timeout', 'offline', 'network', 'server', 'rate_limit'].includes(lastError.kind);
        if (!transient || attempt + 1 >= attempts || opts.signal?.aborted) throw lastError;
        await abortableDelay(Math.min(1200, 250 * (attempt + 1)), opts.signal);
        if (opts.signal?.aborted) throw new ApiError('cancelled', 'Request cancelled');
      } finally {
        clearTimeout(timer);
        opts.signal?.removeEventListener('abort', onAbort);
      }
    }
    throw lastError;
  }

  global.SC_API = Object.freeze({ ApiError, auth, request, beginGeneration, isCurrent });
})(window);
