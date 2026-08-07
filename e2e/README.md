# SpeakChain critical E2E

This harness exercises the checked-out static app without contacting production.

- A local Node server serves repository assets with `no-store` responses.
- Every non-local request is intercepted. Known SDK scripts receive inert stubs, known backend routes receive deterministic fixtures, and every other request fails the test.
- The browser clock, learner identity, Telegram `initData`, session tokens and payloads are fixed.
- The same critical paths run in desktop Chromium and a mobile Chromium viewport.
- Service workers are blocked so cached responses cannot bypass the network allowlist.

Run locally:

```text
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm run validate:e2e
pnpm run e2e
```

The tests never submit a payment, message a learner, use a production secret, or call the production backend. Add a route explicitly to `fixtures/critical-app.js` whenever a new intentional backend dependency is introduced; do not weaken the deny-by-default rule.
