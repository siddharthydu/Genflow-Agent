"""Experimental UI automation; no private endpoints, cookies export or alternative generators."""
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from .core import Blocked, Cancelled


class FlowBrowser:
    def __init__(self, store):
        self.store = store
        self.context = None
        self.page = None
        self.pw = None

    def load_config(self):
        path = self.store.root / 'flow.json'
        if not path.exists():
            raise Blocked('Flow browser profile is not configured. Open Settings → Flow setup.')
        config = json.loads(path.read_text())
        validate_config(config)
        if not config.get('enabled'):
            raise Blocked('Flow browser automation is disabled. Calibrate on the live website first.')
        return config

    def open(self, config):
        if self.context:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise Blocked('Playwright browser runtime is not installed on this server.') from None
        try:
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.connect_over_cdp('http://127.0.0.1:9222')
            self.context = self.browser.contexts[0]
            pages = [p for p in self.context.pages if urlparse(p.url).hostname in ('labs.google', 'flow.google.com', 'accounts.google.com')]
            self.page = pages[0] if pages else self.context.new_page()
            if self.page.url == 'about:blank':
                self.page.goto(config['project_url'], wait_until='domcontentloaded', timeout=60000)
        except Exception:
            self.close()
            raise Blocked('Could not open Flow browser. Check desktop runtime and sign in manually through the protected desktop.') from None

    def close(self):
        try:
            if self.pw:
                self.pw.stop()
        finally:
            self.context = self.page = self.pw = None

    def generate(self, prompt, target, references, cancel, on_submit):
        config = self.load_config()
        self.open(config)
        try:
            page = self.page
            # The authenticated browser remains on the user's Flow project. No sign-in automation.
            if urlparse(page.url).hostname not in ('labs.google', 'flow.google.com'):
                raise Blocked('Flow sign-in required. Open the private desktop and sign in yourself.')
            if page.url != config['project_url']:
                page.goto(config['project_url'], wait_until='domcontentloaded', timeout=60000)
            for key in ('prompt', 'submit'):
                if page.locator(config[key]).count() != 1:
                    raise Blocked('Flow selector '+key+' is not unique. Recalibrate the live page.')
            baseline = page.locator(config['tile']).count()
            if references:
                selector = config.get('reference_input')
                if not selector or page.locator(selector).count() != 1:
                    raise Blocked('Character reference upload control is not calibrated.')
                page.locator(selector).set_input_files([str(p) for p in references])
            page.locator(config['prompt']).fill(prompt)
            cancel()
            # Persist intent BEFORE click. Any subsequent timeout has an ambiguous billing outcome.
            on_submit()
            page.locator(config['submit']).click(timeout=15000)
            started = time.monotonic()
            while time.monotonic()-started < config.get('timeout_seconds', 600):
                cancel()
                count = page.locator(config['tile']).count()
                if count > baseline+1:
                    raise Blocked('Multiple new Flow results appeared. Reconcile manually; one output per shot is required.')
                if count == baseline+1:
                    tile = page.locator(config['tile']).nth(baseline)
                    download = tile.locator(config['download'])
                    if download.count() == 1 and download.is_visible() and download.is_enabled():
                        with page.expect_download(timeout=60000) as info:
                            download.click()
                        info.value.save_as(str(target))
                        if info.value.failure():
                            raise Blocked('Flow download failed. Reconcile the result before resubmission.')
                        cancel()
                        return target
                time.sleep(1)
            raise Blocked('Flow generation timed out. Check login, credits, policy notices and the existing result before resuming.')
        except (Blocked, Cancelled):
            raise
        except Exception:
            raise Blocked('Flow UI operation failed. Submission may have succeeded. Reconcile before retrying; no automatic resubmission.') from None


def validate_config(config):
    if not isinstance(config, dict):
        raise Blocked('Invalid Flow configuration')
    url = urlparse(str(config.get('project_url', '')))
    if url.scheme != 'https' or url.hostname not in ('labs.google', 'flow.google.com') or url.username or url.password or url.port not in (None, 443):
        raise Blocked('Flow project URL must be HTTPS on labs.google or flow.google.com')
    for key in ('prompt', 'submit', 'tile', 'download'):
        if not isinstance(config.get(key), str) or not 1 <= len(config[key]) <= 500:
            raise Blocked('Flow setup needs a calibrated '+key+' selector')
    if not isinstance(config.get('timeout_seconds', 600), int) or not 60 <= config.get('timeout_seconds', 600) <= 1800:
        raise Blocked('Flow timeout must be 60–1800 seconds')
