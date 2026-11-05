# GenFlow: Android-only setup

This guide is executable from an Android browser, but its cloud deployment steps have not been performed in this session. A computer is not required; a persistent paid cloud VM and an HTTPS hostname are required. The GitHub repository URL is not yet available because the connector currently sees no repositories. Do not enter any Google password, OTP, cookies or session tokens into ChatGPT or GitHub secrets.

## 1. Give GitHub access

1. In Chrome on Android, open https://github.com/new and choose **Desktop site** if needed.
2. Create a **private** repository named `GenFlow`. Add a README so it has an initial commit. Keep the default branch `main`.
3. Open GitHub Settings → Applications → Installed GitHub Apps → the app used for your ChatGPT GitHub connection → Configure. Grant access to `GenFlow`. If using OAuth instead, reconnect the GitHub integration and authorize the repository.
4. Paste only the repository URL back into this conversation. Do not paste a token. Source can then be pushed through the connected GitHub tools.

Until step 4 and a successful push, the included Actions YAML is source code on disk, not a configured cloud build or completed workflow run.

## 2. Build and download the APK

After source is actually in the repository:

1. Open the repository → **Actions** → **GenFlow Android and backend checks**.
2. If prompted, enable Actions for your own private repository. GitHub plan quotas may apply.
3. Choose **Run workflow** → `main` → **Run workflow**. A push to `main` also starts it.
4. Wait for `backend` and `apk` to turn green. If a job fails, open its log; do not assume an APK exists.
5. Open the successful run → Artifacts → **GenFlow-Android-APK**. Download the ZIP and use Android Files to extract **GenFlow.apk**. This ZIP is GitHub's artifact container, not a project scaffold.
6. Tap `GenFlow.apk`, permit installation from your browser/file manager when Android asks, and install.

The default APK is development-signed. It is installable, but a debug signing key on ephemeral runners is not a stable distribution identity. A later build might require uninstalling the previous development build. A stable signed release uses `release.yml` and a private keystore. A development-signed APK was produced locally and its signature verified; installation on a real Android device has not been tested. The delivered APK can be installed directly; the steps above describe future GitHub builds once source is published.

### Optional stable release key

Use your cloud VM's browser terminal (not ChatGPT) to run:

```bash
keytool -genkeypair -v -keystore genflow-release.jks -alias genflow -keyalg RSA -keysize 3072 -validity 10000
base64 -w 0 genflow-release.jks
```

Copy the output privately into GitHub repository Settings → Secrets and variables → Actions → New repository secret: `GENFLOW_KEYSTORE_BASE64`. Add `GENFLOW_STORE_PASSWORD`, `GENFLOW_KEY_ALIAS` (`genflow`) and `GENFLOW_KEY_PASSWORD`. Keep an encrypted offline backup of the keystore and passwords; never commit them. Run **GenFlow signed release** and download **GenFlow-Signed-Release-APK** only after the run succeeds.

## 3. Prepare a persistent cloud VM

Use a provider whose web console includes a browser terminal or SSH console. Suggested deployment shape, not a tested capacity guarantee: Ubuntu 24.04 x86_64, 2–4 vCPUs, 8 GB RAM and at least 80 GB persistent disk. Browser generation and FFmpeg compete for memory; scale up for longer episodes. This is not a serverless deployment and the VM must remain running.

1. Create the VM using your provider's Android-accessible dashboard. Review its actual price before provisioning.
2. Point an owned hostname, for example `genflow.yourdomain.com`, to the VM public IP using a DNS A record. Remove an unrelated AAAA record if the VM has no IPv6.
3. Allow TCP 80/443 inbound. Restrict SSH to your access method/IP. Do **not** expose 5900, 6080, 8080 or 9222 publicly. The Compose file only publishes 80/443.
4. Use the provider's browser terminal. Install Docker Engine with its Compose plugin using Docker's official Ubuntu instructions: https://docs.docker.com/engine/install/ubuntu/ . Confirm `docker compose version` works. Your shell account must have Docker access; use `sudo` if required. Docker access is effectively host administrative access.
5. Clone the private repository. Prefer GitHub CLI's browser/device login from your terminal (`gh auth login` → GitHub.com → HTTPS → browser login), then `gh repo clone YOUR_ACCOUNT/GenFlow`. Enter the displayed device code only on GitHub's page. Do not share it here. Alternatively use an SSH key added to GitHub from the provider terminal.
6. Change to the project folder and create the private configuration:

```bash
cd GenFlow/deploy
umask 077
cp .env.example .env
nano .env
```

Set `GENFLOW_DOMAIN`, `GEMINI_API_KEY`, and `GEMINI_MODEL`. Create the Gemini key only in your own Google AI Studio/API project, enable appropriate billing/quota, and choose a model that currently supports text and video understanding. This key is for planning/analysis only; video generation remains Google Flow. Keep it in this server file. Your ChatGPT subscription is not a substitute for an API key.

Generate a separate desktop password hash interactively:

```bash
docker run --rm -it caddy:2.10.2-alpine caddy hash-password
```

Enter a strong, unique desktop password when prompted. Put its resulting bcrypt hash inside **single quotes** as `GENFLOW_DESKTOP_HASH` in `.env`; the desktop username is `studio`. Never reuse your Google password.

## 4. Start the backend

From `GenFlow/deploy` in the VM terminal:

```bash
docker compose build
docker compose run --rm genflow python -m genflow.server --init
docker compose up -d
docker compose ps
docker compose logs --tail 80 genflow
```

The init command prompts privately for a GenFlow admin password of at least 16 characters. Use a different password from the desktop and Google passwords. If Chromium reports sandbox or namespace errors, resolve the VM's user-namespace/seccomp support. Do not expose CDP or disable authentication to work around setup problems. Container build, Chromium startup, Caddy TLS issuance and noVNC have not been tested here.

In Android Chrome open `https://YOUR_HOST/health`. It should return `{"service":"GenFlow","status":"ok"}` after Caddy obtains a valid TLS certificate. A health response verifies the API process, not Flow login or end-to-end generation.

Open GenFlow on Android, enter `https://YOUR_HOST` and the GenFlow admin password. No trailing `/api` is needed. The app intentionally refuses HTTP and invalid certificates.

## 5. Sign into Google Flow privately

1. App → Settings → **Open private Flow desktop**.
2. Authenticate to the desktop as `studio` using your separate desktop password.
3. A visible Chromium browser should open Google Flow. Sign in to Google yourself. Your credentials and session stay in that browser profile on your VM's persistent disk.
4. Complete any legitimate Google verification yourself. If Google rejects the hosted/automated browser, stop automation. Do not attempt CAPTCHA bypass or transfer cookies from another device.
5. Create/open a Flow project. Set **one output per generation**, requested aspect/duration, video mode and audio settings. Use an append-ordered project/list the adapter can unambiguously identify.
6. Follow [GOOGLE_FLOW_SETUP.md](GOOGLE_FLOW_SETUP.md). No guessed selectors are supplied as verified defaults.

## 6. Produce an episode

1. Projects → New project. Add character names, detailed identities, voice/accent and default clothing. Upload JPEG portraits before starting the job. Portraits remain reusable; each episode snapshots the current bible.
2. Episodes → New episode. Select project, paste command and optional script, choose 16:9/9:16, attempts per shot and total generation limit.
3. For deterministic preservation use one spoken line per line, e.g. `Mohan: Sharda, hum phir se shuru karenge.` Character names must match the bible. Very long lines may be split, but the combined words/speaker order must remain exact. Prose scripts with spoken dialogue but no recognized speaker lines are blocked; create a new episode using the corrected script.
4. Queue. Missing API access, browser configuration, Google credits or login pauses the job with a visible reason. Configure the missing service, then Resume.
5. For uncertain QA, play the clip and inspect the evidence. Approve only after checking face, clothes, voice, exact dialogue and lip sync. First-clip voice identity normally requires human review because a portrait cannot establish a voice.
6. If Flow submission times out, inspect the existing Flow result first. Import that clip into its shot. Only explicitly retry when you accept potential duplicate credit use.
7. Once all shots are approved, the worker exports MP4. Tap **Save final MP4** and choose an Android folder. Interrupted downloads may leave a partial destination; retry saving after fixing connectivity.

## Operations and backup

- Stop jobs in the app before changing Flow settings or operating its project manually.
- App resume survives phone disconnects; work lives on the VM. The app polls while visible; background push notifications are not implemented.
- Restart safely: `docker compose restart genflow`. Ambiguous submissions will pause after worker recovery.
- Update: back up, `git pull --ff-only`, `docker compose build`, then `docker compose up -d`. Only schema version 1 currently exists; no historical migration has been exercised.
- Reset forgotten admin password: `docker compose exec genflow python -m genflow.server --init`. Existing sessions are revoked.
- Back up the `genflow-data` Docker volume using provider disk snapshots or a stopped-container volume backup. It contains sensitive scripts, clips and the Google browser session. Encrypt backups and keep them private. Do not upload browser profiles to GitHub or ChatGPT.
- No automatic retention deletion exists; monitor disk usage and take backups before removing old media. Do not manually delete SQLite files while the service is running.

## Concrete Google Cloud VM path (optional, not executed)

This is one provider-specific path if you have no VM yet. It creates billable resources. Use your own Google Cloud project with billing enabled and adequate Compute/IAP permissions. Verify its displayed pricing and set a billing budget in the console first; no fixed monthly price is promised. On Android Chrome, open https://console.cloud.google.com/ , enable Desktop site and open **Cloud Shell**. If the mobile terminal cannot accept commands reliably, use the provider's separate browser terminal or an Android SSH app; this mobile UI has not been tested in this session.

In Cloud Shell, replace the project id below with your actual project id:

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable compute.googleapis.com iap.googleapis.com oslogin.googleapis.com
gcloud compute networks create genflow-network --subnet-mode=auto
gcloud compute firewall-rules create genflow-web --network=genflow-network --allow=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 --target-tags=genflow-web
gcloud compute firewall-rules create genflow-iap-ssh --network=genflow-network --allow=tcp:22 --source-ranges=35.235.240.0/20 --target-tags=genflow-web
gcloud compute addresses create genflow-ip --region=asia-south1
gcloud compute addresses describe genflow-ip --region=asia-south1 --format='value(address)'
```

Copy the returned IP into the `--address` value below. These are new-resource commands; if a resource already exists, inspect it instead of repeatedly recreating it.

```bash
gcloud compute instances create genflow --zone=asia-south1-a --machine-type=e2-standard-2 --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud --boot-disk-size=80GB --boot-disk-type=pd-balanced --network=genflow-network --tags=genflow-web --address=YOUR_RESERVED_IP --metadata=enable-oslogin=TRUE --no-service-account --no-scopes
gcloud compute ssh genflow --zone=asia-south1-a --tunnel-through-iap
```

The account may need `roles/iap.tunnelResourceAccessor`, OS Login/OS Admin Login and Compute permissions granted by its administrator. Do not broaden access to work around an organization policy. DNS must point to the reserved IP before Caddy can obtain a certificate.

Within the VM shell, install Docker with its official APT repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git nano
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Create the repository file:

```bash
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<'DOCKER'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
DOCKER
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker compose version
```

Use `sudo docker ...` for the Docker commands in this guide unless you explicitly configure your operator account's Docker access. Clone the private GitHub repository through browser/device auth or SSH, then follow steps 3–6 above. These instructions prepare a deployment path; they are not a deployed backend URL or a passed cloud smoke test.

Primary references: https://docs.cloud.google.com/compute/docs/create-linux-vm-instance , https://docs.cloud.google.com/compute/docs/connect/ssh-using-iap , https://docs.docker.com/engine/install/ubuntu/ .
