# GenFlow

Android-controlled production orchestration with Google Flow as the exclusive AI video generator.

**Delivery status:** real backend and Android source have been implemented; local backend/media tests pass. The app is **not yet an end-to-end verified working product**. A development-signed Android APK has been built locally and its signature verified. No repository push, cloud deployment, Android device installation, authenticated Flow generation or live Gemini QA has been completed in this session. See the exact prerequisites in [architecture and feasibility audit](docs/ARCHITECTURE.md).

## Source

- `android/`: native Java Android app; HTTPS login, encrypted session storage, reusable characters/portraits, episode queue, progress/cancellation, clip review/import and MP4 save.
- `backend/genflow/`: durable SQLite orchestration, official Gemini planning/video analysis, experimental Google Flow browser adapter, technical QA, retry budgets, recovery and FFmpeg export.
- `backend/tests/`: synthetic local tests; no tests pretend to generate Google Flow video.
- `.github/workflows/android.yml`: backend tests, Android build/lint and downloadable development-signed APK artifact, plus cloud-image build.
- `.github/workflows/release.yml`: optional release-signed APK using private Actions secrets.
- `deploy/`: persistent Docker Compose VM deployment with Caddy TLS, protected noVNC desktop and visible Chromium. Deployment is not yet exercised.

## Setup and evidence

1. [Android-only setup and deployment](docs/ANDROID_ONLY_SETUP.md)
2. [Google Flow integration and live calibration](docs/GOOGLE_FLOW_SETUP.md)
3. [Actual test report](docs/TEST_REPORT.md) and [raw output](docs/test-output.txt)
4. [API reference](docs/API.md)
5. [Security and operational boundaries](SECURITY.md)

Local backend tests (Python 3.12+, FFmpeg required):

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
```

Android build (JDK 17, Gradle 8.9, Android SDK 35):

```bash
cd android
gradle --no-daemon :app:assembleDebug :app:lintDebug
```

No Google credentials, provider API keys, Android keystores or browser sessions belong in this repository. Missing services pause with a visible blocker. A local test pass does not imply Google Flow compatibility, reliable Google cloud-browser login or production deployment readiness.
