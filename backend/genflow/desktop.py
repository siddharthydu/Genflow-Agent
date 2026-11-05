"""Start a visible, persistent browser. Google sign-in is performed manually over noVNC."""
import os
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

if __name__ == '__main__':
    root = Path(os.getenv('GENFLOW_DATA', '/data'))
    profile = root/'browser-profile'
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sync_playwright() as pw:
        executable = pw.chromium.executable_path
    subprocess.run([executable, '--user-data-dir='+str(profile), '--remote-debugging-address=127.0.0.1',
                    '--remote-debugging-port=9222', '--no-first-run', '--window-size=1440,900',
                    'https://flow.google.com/'], check=True)
