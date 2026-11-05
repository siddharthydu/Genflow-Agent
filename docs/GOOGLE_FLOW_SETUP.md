# Google Flow integration: verified facts and experimental adapter

Research checked 5 November 2026.

## What is officially supported

Google documents Flow's own UI/Agent for planning, prompt refinement, batch generation, references and organization:
https://support.google.com/labs/answer/17093911?hl=en
The inspected help page describes the Agent as web/PC only and says generated media uses Google Flow credits. Its confirmation and default generation settings are controlled inside Flow.

A separate official Gemini video-generation API exists:
https://ai.google.dev/gemini-api/docs/video
This is not evidence of an external Google Flow project API. GenFlow does **not** call it, even when a related model is available there. The requirement is exclusively Google Flow for generated video.

No official public external Flow API or supported third-party unattended job contract was established from the inspected official Flow pages. This is a research finding, not proof that Google can never add an API. Recheck before future integration changes. Third-party services advertising a 'Flow API' are not Google's supported Flow API and are not integrated here.

## What this adapter does

Playwright attaches to a visible persistent Chromium browser running on your private VM. The user signs in manually over a password-protected TLS desktop. The adapter fills the visible prompt, optionally uploads JPEG references, clicks Generate, waits for exactly one new result tile and clicks that tile's download button.

This is browser automation, not an officially supported Flow API. It is experimental and has not been exercised against a signed-in Flow account in this session. Google may reject cloud-browser login, revoke sessions, change controls, reorder results, add menus, show unusual-activity warnings or require human interaction. A successful unit test with a test double is not live compatibility evidence.

No private Google endpoints, cookie copying, credential scraping, reCAPTCHA bypass or anti-detection patches are implemented. If blocked, pause and use manual generation/import through Google Flow. Manual import is an operational fallback within the required generator, not autonomous video generation.

## Calibrating the live page

A browser automation engineer must inspect your actual signed-in UI. This is an outstanding setup step; it cannot honestly be replaced by a universal guessed selector. From your protected VM desktop, use Chromium DevTools or Playwright's locator inspector. Android can operate this remote desktop, although selector inspection is difficult on a small screen.

The JSON settings fields are:

| Field | Meaning |
|---|---|
| `enabled` | Keep `false` until a live one-shot validation succeeds and limits are set |
| `project_url` | Exact HTTPS URL on `flow.google.com` or `labs.google` of the signed-in project |
| `prompt` | Unique editable prompt control selector |
| `submit` | Unique visible Generate button selector |
| `tile` | Selector for generated result cards; stable append order required |
| `download` | Direct download control selector **relative to a single result tile** |
| `reference_input` | Unique file input supporting the current shot's JPEG references, if characters need portraits |
| `timeout_seconds` | 60–1800, default 600 |

Selectors are standard Playwright selector strings. Do not include credentials or network tokens. Do not use a selector that matches old videos, images or other users' outputs. The adapter requires one result per submit and refuses ambiguous multiple new results.

Live validation procedure:

1. Disable automation; clear pending manual generations in the dedicated project.
2. Set video mode, aspect, audio and one output in Flow manually. No API or app setting is falsely assumed to change the website's controls.
3. Verify prompt/submit selectors each resolve to exactly one control.
4. Upload references and verify Flow uses them and replaces prior-shot references rather than accumulating duplicates.
5. Make one deliberately short live generation under an explicit small credit budget. Observe result ordering, whether the tile appears before completion and whether the direct download emits a browser download event.
6. Check the downloaded file belongs to the new shot, not an old generation. Compare actual spoken words and visible reference identity.
7. Exercise a failed/timeout generation and verify GenFlow pauses in `submitting` rather than resubmitting.
8. Only then treat that **specific** selector profile/site version/account as validated, record date/settings in your deployment notes and enable automation for a small episode.

If Flow uses a menu to choose download resolution, virtualized cards, newest-first sorting or a custom reference picker, the current adapter needs implementation changes. Merely filling JSON cannot make those flows work. Do not claim this source has solved those UI variants. App Settings warns that saving configuration is not a compatibility check.

## Quality checks

Deterministic media checks: full FFmpeg decode, tracks, resolution, aspect, planned duration, near-black content and silent spoken dialogue. Export preserves native dialogue; it does not synthesize or replace voices.

Semantic checks: configurable official Gemini video-understanding API analyzes the clip and reference media for face, appearance, wardrobe, voice, dialogue, lip sync, sound, shot requirements, visual quality and continuity. All required checks must be returned; missing checks fail closed. Perceptual lip-sync assessment is not forced alignment; identity matching is not a measured biometric guarantee. Any `uncertain` result pauses for documented human review.

A portrait cannot establish voice identity. Your first approved clip becomes a previous-clip reference for subsequent shots. Non-adjacent-character voice consistency is currently described in the bible and perceptually checked; a persistent reference voice library and objective speaker verification are not implemented. Fully autonomous perfect consistency has not been established.
