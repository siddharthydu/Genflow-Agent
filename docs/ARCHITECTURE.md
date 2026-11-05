# GenFlow architecture and feasibility audit

Status: implemented source, locally built/signature-verified Android APK, clean Android lint and 35 passing backend tests; not an end-to-end verified product.
Assessment date: 5 November 2026. No Google generation was performed in this session.

## Capability checks and exact blockers

| Capability | Observed result | Consequence / prerequisite |
|---|---|---|
| GitHub identity | Connected account `siddharthydu` resolved | Identity check succeeded |
| Repository access | Repository list and installation list both empty | User must create/select a repository and grant connector access; no source has been published |
| Repository creation | No create-repository action exposed by connector | Cannot create an account repository from this session |
| Coding | Filesystem, Python, Java 17, git, FFmpeg available | Backend can be implemented and exercised locally |
| Android toolchain | SDK/Gradle initially absent; acquired through direct downloads; full JDK added after missing jlink | Local build and lint passed; no emulator/device available |
| Dependency downloads | Initial redirect/proxy attempts failed; direct downloads and private Gradle proxy configuration succeeded | Android dependencies acquired; browser execution still blocked by sandbox Unix-socket restriction |
| Cloud deployment | No VM/provider account or cloud credentials connected | Cannot provision a persistent service or publish a real backend URL |
| Flow session | No authenticated Flow project available | Cannot calibrate selectors, submit a prompt, inspect actual output or validate download mapping |
| Flow API | No public third-party application API established in inspected official Flow docs | Browser adapter is experimental and disabled until configured; supported Gemini video API is a different product and is not used |
| AI planning and semantic QA | No Gemini API key/model configured | Live text planning and video analysis cannot be tested; missing configuration blocks the job |
| Google subscription | Flow plan/credits not verified | Generation needs the user's own eligible Flow access and credits |
| Android release signing | No private release keystore supplied | CI can build development-signed installable APK; stable release signing requires private GitHub secrets |
| Perfect identity/voice/lip sync | No calibrated biometric/forced-alignment evaluators or live benchmark corpus | Perceptual model checks are estimates; uncertain checks require human review |

These are prerequisites, not permission to substitute generators or claim mocked calls are live integration tests.

## Components

- **Android:** native Java application, Android 8.0+, no third-party UI SDK; HTTPS-only client, Android Keystore AES-GCM session storage, projects/characters, JPEG portraits, episode command/script, configurable budgets, progress polling, cancellation, clip playback/import, human QA and MP4 save through Android's document picker.
- **API:** Python standard-library threaded HTTP service behind Caddy TLS. Single-tenant administrator authentication, scrypt password hashing, hashed expiring sessions, login throttling, bounded connections and upload sizes. No embedded provider credentials in APK or repository.
- **Persistence:** SQLite WAL database in a Docker named volume. Jobs, immutable episode character snapshots, shot specifications/prompts, attempts, QA, events and export paths are durable. Originals and retries remain in `/data/media`; browser profile stays in a separate private directory in the same persistent volume.
- **Worker:** one process protected by an OS file lock. SQLite atomic claim prevents double-processing. Safe interrupted work is requeued. Ambiguous external submissions pause for reconciliation rather than being blindly replayed.
- **Planning/analysis:** official Gemini REST endpoint for text and video understanding only. The operator selects a currently available model; there is no hidden outdated model default. The provider gets script, references and analysis clips when this feature is used. It never receives Google account credentials.
- **Generation:** visible Chromium, manually authenticated in Google Flow over a separately protected noVNC desktop. Playwright connects to CDP bound only to loopback. Generation uses visible page controls; no undocumented RPCs, copied bearer tokens, session export, CAPTCHA evasion or alternative video-generation providers.
- **Media:** FFmpeg decodes and validates clips, checks tracks, dimensions, aspect, duration, almost-black frames and silent dialogue. Export normalizes resolution, timestamps, frame rate and audio format, then concatenates in shot order to H.264/AAC MP4 with faststart.

## State and recovery

Jobs: `queued → running → completed`; any active stage can become `blocked`, `failed` or `cancelled`. An explicit resume requeues a safe job.

Shots: `pending → submitting → downloaded → analyzing → approved/review/rejected`.
A rejected clip is retained and the next prompt includes defects, subject to per-shot attempts and episode-wide generation budget. An uncertain clip pauses in `review`. Operator approval records a note and preserves the model evidence. A `submitting` shot after a timeout/crash requires importing its existing clip or explicitly acknowledging duplicate credit risk.

The database write occurs before the external submit click. This intentionally favors a false ambiguity over silently spending twice. Google Flow cannot be rolled back transactionally. Cancellation stops subsequent submissions and local rendering; a generation already accepted by Google may finish and consume credits. Analysis HTTP calls have a 180-second timeout and are checked for cancellation before/after, so cancellation may not appear instantaneous during an in-flight analysis request.

## Boundaries and unfinished validation

This is a single-owner deployment, not a multi-tenant commercial service. Persistent disks are not off-site backups. Automatic clip import verifies file content but cannot cryptographically prove a file originated in Flow. The operator must import only Google Flow clips.

AI planning can make mistakes. `Name: dialogue` lines receive an exact ordered comparison (whitespace normalized), stopping before spending Flow credits if the plan changes them. Prose scripts with dialogue but without recognized speaker lines are blocked before generation and must be reformatted. Model-based semantic QA does not prove exact ASR alignment, identity embeddings or objective lip-sync accuracy. Voice references start with a manually reviewed first clip; JPEG portraits alone cannot establish a voice identity.

No browser control profile is bundled as 'known working'. Selector calibration, reference upload behavior, output order and download menu behavior must be validated on the actual signed-in Flow UI. If the website sorts newest-first, batches outputs, virtualizes cards, has an intermediate download menu or blocks automated browsers, this adapter needs adjustment before use. Do not enable it based only on the local unit tests.
