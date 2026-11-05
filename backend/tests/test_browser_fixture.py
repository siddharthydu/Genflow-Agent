"""Real Chromium exercising a synthetic page, NOT the Google Flow service."""
import base64
import importlib.util
import json
import os
import socket
from pathlib import Path
import tempfile
import unittest
from genflow.core import Store, Blocked
from genflow.flow import FlowBrowser

def unix_sockets_available():
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.close()
        return True
    except OSError:
        return False

ENABLED = bool(os.getenv('GENFLOW_TEST_CHROMIUM')) and importlib.util.find_spec('playwright') is not None and unix_sockets_available()


@unittest.skipUnless(ENABLED, 'Requires Playwright, GENFLOW_TEST_CHROMIUM and permitted Unix sockets; current sandbox cannot run Chromium')
class BrowserFixtureTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        executable = os.getenv('GENFLOW_TEST_CHROMIUM')
        self.browser = self.pw.chromium.launch(headless=True, executable_path=None if executable == 'auto' else executable)
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        self.payload = b'GenFlow synthetic browser-download fixture; not generated video'
        self.config = {'enabled': True, 'project_url': 'https://flow.google.com/genflow-local-fixture',
                       'prompt': '#prompt', 'submit': '#submit', 'tile': '.result',
                       'download': 'a', 'reference_input': '#reference', 'timeout_seconds': 60}
        (self.store.root/'flow.json').write_text(json.dumps(self.config))
        self.adapter = FlowBrowser(self.store)
        self.adapter.context, self.adapter.page = self.context, self.page

    def tearDown(self):
        self.context.close(); self.browser.close(); self.temp.cleanup()

    def fixture(self, multiple=False, duplicate_prompt=False):
        payload = base64.b64encode(self.payload).decode()
        html = '''<!doctype html><textarea id="prompt"></textarea><input type="file" multiple id="reference">
        <button id="submit">Generate fixture</button><main id="results"></main><script>
        document.querySelector('#submit').onclick=()=>{for(let i=0;i<COUNT;i++){
        let tile=document.createElement('div');tile.className='result';
        let a=document.createElement('a');a.download='fixture.mp4';a.href='data:video/mp4;base64,PAYLOAD';
        a.textContent='Download';tile.append(a);document.querySelector('#results').append(tile);}};</script>'''
        html = html.replace('COUNT', '2' if multiple else '1').replace('PAYLOAD', payload)
        if duplicate_prompt:html += '<textarea id="prompt"></textarea>'
        self.page.route('https://flow.google.com/**', lambda route: route.fulfill(status=200,content_type='text/html',body=html))
        self.page.goto(self.config['project_url'])

    def test_prompt_reference_submit_and_download_on_synthetic_page(self):
        self.fixture(); reference = self.store.root/'portrait.jpg'; reference.write_bytes(b'fixture portrait')
        target = self.store.media/'fixture.mp4'; submissions=[]
        self.adapter.generate('Exact dialogue: Main kal aaunga.', target, [reference], lambda: None, lambda: submissions.append(True))
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertEqual(self.page.locator('#prompt').input_value(), 'Exact dialogue: Main kal aaunga.')
        self.assertEqual(self.page.locator('#reference').evaluate('(e)=>e.files.length'), 1)
        self.assertEqual(submissions,[True])

    def test_non_unique_controls_stop_before_submission(self):
        self.fixture(duplicate_prompt=True); submissions=[]
        with self.assertRaises(Blocked):self.adapter.generate('test',self.store.media/'x.mp4',[],lambda:None,lambda:submissions.append(True))
        self.assertEqual(submissions,[])

    def test_multiple_new_results_pause_without_downloading_wrong_clip(self):
        self.fixture(multiple=True); submissions=[]; target=self.store.media/'x.mp4'
        with self.assertRaises(Blocked):self.adapter.generate('test',target,[],lambda:None,lambda:submissions.append(True))
        self.assertEqual(submissions,[True]);self.assertFalse(target.exists())


if __name__ == '__main__':unittest.main(verbosity=2)
