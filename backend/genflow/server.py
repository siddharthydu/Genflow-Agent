import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import urlsplit
from .core import Auth, Blocked, Problem, Store, encoded, uid
from .flow import validate_config
from .media import probe, technical_qa

ID = r'([a-f0-9]{32})'


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    def __init__(self, address, store):
        self.store, self.auth = store, Auth(store)
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'GenFlow'
    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def log_message(self, *_):
        pass  # Do not log credentials, scripts or user media URLs.

    def json_body(self):
        length = self.body_length(2_000_000)
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError):
            raise Problem('JSON object required') from None

    def body_length(self, maximum):
        if self.headers.get('Transfer-Encoding'):
            raise Problem('Chunked uploads not supported; use Content-Length', 411)
        try:
            length = int(self.headers.get('Content-Length', '-1'))
        except ValueError:
            length = -1
        if not 0 <= length <= maximum:
            raise Problem('Missing or excessive Content-Length', 413)
        return length

    def send_json(self, data, status=200):
        body = encoded(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def stream(self, path, filename):
        size = path.stat().st_size
        start, end, status = 0, size-1, 200
        range_header = self.headers.get('Range')
        if range_header:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', range_header)
            if not match:
                raise Problem('Unsupported byte range', 416)
            start = int(match[1])
            end = min(int(match[2]), size-1) if match[2] else size-1
            if not 0 <= start <= end < size:
                raise Problem('Invalid byte range', 416)
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Content-Disposition', 'attachment; filename="'+filename+'"')
        self.send_header('Content-Length', str(end-start+1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'private, no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start)
            remaining = end-start+1
            while remaining:
                chunk = f.read(min(1_048_576, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def save_upload(self, suffix, maximum):
        length = self.body_length(maximum)
        path = self.server.store.media/(uid()+suffix)
        partial = path.with_suffix('.part')
        try:
            with partial.open('xb') as f:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1_048_576, remaining))
                    if not chunk:
                        raise Problem('Incomplete upload')
                    f.write(chunk)
                    remaining -= len(chunk)
            partial.replace(path)
            return path
        finally:
            partial.unlink(missing_ok=True)

    def dispatch(self):
        route = urlsplit(self.path).path
        method, store = self.command, self.server.store
        if method == 'GET' and route == '/health':
            self.send_json({'service': 'GenFlow', 'status': 'ok'})
            return
        if method == 'POST' and route == '/api/login':
            data = self.json_body()
            self.send_json(self.server.auth.login(data.get('password', ''), self.client_address[0]))
            return
        digest = self.server.auth.require(self.headers.get('Authorization', ''))
        if method == 'POST' and route == '/api/logout':
            store.execute('DELETE FROM sessions WHERE hash=?', (digest,))
            self.send_json({'ok': True})
        elif route == '/api/projects' and method == 'GET':
            self.send_json({'projects': store.rows('SELECT * FROM projects ORDER BY created DESC')})
        elif route == '/api/projects' and method == 'POST':
            self.send_json(store.project(self.json_body()), 201)
        elif (m := re.fullmatch('/api/projects/'+ID+'/characters', route)) and method == 'POST':
            project = store.one('SELECT * FROM projects WHERE id=?', (m[1],))
            character = self.json_body()
            chars = json.loads(project['characters'])
            if not character.get('name') or not character.get('identity') or len(encoded(character)) > 16000 or len(chars) >= 30:
                raise Problem('Character needs a name and identity; maximum 30 characters')
            if any(c['name'].casefold() == str(character['name']).casefold() for c in chars):
                raise Problem('Character name already exists')
            chars.append(character)
            store.execute('UPDATE projects SET characters=? WHERE id=?', (encoded(chars), m[1]))
            self.send_json({'characters': chars}, 201)
        elif (m := re.fullmatch('/api/projects/'+ID+r'/characters/(\d+)/reference', route)) and method == 'POST':
            project = store.one('SELECT * FROM projects WHERE id=?', (m[1],))
            chars = json.loads(project['characters'])
            index = int(m[2])
            if not 0 <= index < len(chars):
                raise Problem('Invalid character index')
            path = self.save_upload('.jpg', 8_000_000)
            try:
                with path.open('rb') as f:
                    if f.read(3) != b'\xff\xd8\xff':
                        raise Problem('Upload a JPEG portrait')
                info = probe(path)
                video = next(s for s in info['streams'] if s['codec_type'] == 'video')
                if video['width'] < 128 or video['height'] < 128:
                    raise Problem('Portrait must be at least 128 × 128')
            except Exception:
                path.unlink(missing_ok=True)
                raise Problem('Valid JPEG portrait required') from None
            chars[index]['reference_id'] = path.stem
            store.execute('UPDATE projects SET characters=? WHERE id=?', (encoded(chars), m[1]))
            self.send_json({'reference_id': path.stem})
        elif route == '/api/jobs' and method == 'GET':
            self.send_json({'jobs': store.rows('SELECT id,project_id,command,state,error,output,created,updated FROM jobs ORDER BY created DESC LIMIT 200')})
        elif route == '/api/jobs' and method == 'POST':
            self.send_json(store.create_job(self.json_body()), 201)
        elif (m := re.fullmatch('/api/jobs/'+ID, route)) and method == 'GET':
            self.send_json(store.job(m[1]))
        elif (m := re.fullmatch('/api/jobs/'+ID+'/cancel', route)) and method == 'POST':
            job = store.job(m[1])
            if job['state'] == 'completed':
                raise Problem('Completed export cannot be cancelled', 409)
            store.execute('UPDATE jobs SET cancel=1 WHERE id=?', (m[1],))
            if job['state'] != 'running':
                store.set_state(m[1], 'cancelled')
            self.send_json({'ok': True})
        elif (m := re.fullmatch('/api/jobs/'+ID+'/resume', route)) and method == 'POST':
            job = store.job(m[1])
            if job['state'] not in ('blocked', 'failed', 'cancelled'):
                raise Problem('Only a blocked, failed or cancelled job can resume', 409)
            if any(s['state'] == 'submitting' for s in job['shots']):
                raise Problem('Reconcile the unresolved submission before resume', 409)
            store.execute("UPDATE jobs SET cancel=0,state='queued',error=NULL,updated=? WHERE id=?", (time.time(), m[1]))
            store.event(m[1], 'queued', 'User resumed job')
            self.send_json({'ok': True})
        elif (m := re.fullmatch('/api/shots/'+ID+'/(approve|retry|clip)', route)):
            shot = store.one('SELECT * FROM shots WHERE id=?', (m[1],))
            job = store.job(shot['job_id'])
            if m[2] == 'clip' and method == 'GET':
                if not shot['path'] or not (store.media/shot['path']).is_file():
                    raise Problem('Clip not available', 404)
                self.stream(store.media/shot['path'], 'GenFlow-shot.mp4')
                return
            if method != 'POST':
                raise Problem('Method not allowed', 405)
            if job['state'] in ('running', 'queued', 'completed'):
                raise Problem('Pause or cancel the job before modifying a shot', 409)
            if m[2] == 'clip':
                path = self.save_upload('.mp4', 200_000_000)
                try:
                    qa = technical_qa(path, json.loads(shot['spec']), job['settings'])
                    if not qa['approved']:
                        raise Problem('Clip failed technical checks: '+str(qa['issues']), 422)
                except Exception:
                    path.unlink(missing_ok=True)
                    raise
                store.execute("UPDATE shots SET state='uploaded',path=?,qa=NULL WHERE id=?", (path.name, m[1]))
                store.event(job['id'], 'import', 'User imported a Google Flow clip for shot '+str(shot['position']+1))
            else:
                data = self.json_body()
                if len(str(data.get('note', '')).strip()) < 8:
                    raise Problem('A review/reconciliation note (at least 8 characters) is required')
                if m[2] == 'approve':
                    qa = json.loads(shot['qa'] or '{}')
                    if shot['state'] != 'review' or not qa.get('technical', {}).get('approved'):
                        raise Problem('Human approval requires completed technical QA and review state', 409)
                    qa['human_review'] = {'at': time.time(), 'note': data['note']}
                    qa['approved'] = True
                    store.execute("UPDATE shots SET state='approved',qa=? WHERE id=?", (encoded(qa), m[1]))
                else:
                    if shot['state'] == 'submitting' and data.get('acknowledge_duplicate_cost') is not True:
                        raise Problem('Confirm duplicate credit risk after checking the existing Flow result', 409)
                    store.execute("UPDATE shots SET state='pending',path=NULL WHERE id=?", (m[1],))
                    store.execute("UPDATE attempts SET state='reconciled',error=?,finished=? WHERE shot_id=? AND state='submitting'",
                                  (data['note'], time.time(), m[1]))
                store.event(job['id'], 'human_'+m[2], data['note'])
            self.send_json({'ok': True})
        elif (m := re.fullmatch('/api/jobs/'+ID+'/export', route)) and method == 'GET':
            job = store.job(m[1])
            if job['state'] != 'completed' or not job['output']:
                raise Problem('Export not ready', 409)
            self.stream(store.media/job['output'], 'GenFlow-'+m[1][:8]+'.mp4')
        elif route == '/api/config' and method == 'GET':
            path = store.root/'flow.json'
            self.send_json({'flow': json.loads(path.read_text()) if path.exists() else None,
                            'ai_configured': bool(os.getenv('GEMINI_API_KEY') and os.getenv('GEMINI_MODEL')),
                            'flow_status': 'experimental UI adapter, requires live calibration',
                            'desktop_path': '/desktop/vnc.html?autoconnect=1&resize=remote'})
        elif route == '/api/config/flow' and method == 'POST':
            config = self.json_body()
            validate_config(config)
            # Never accept Google credentials/cookies/tokens as configuration.
            allowed = {'enabled','project_url','prompt','submit','tile','download','reference_input','timeout_seconds'}
            if set(config)-allowed:
                raise Problem('Unsupported configuration keys. Never upload account credentials.')
            if store.rows("SELECT id FROM jobs WHERE state='running'"):
                raise Problem('Cancel the current job before changing browser configuration', 409)
            path = store.root/'flow.json'
            temporary = path.with_suffix('.tmp')
            temporary.write_text(encoded(config))
            os.chmod(temporary, 0o600)
            temporary.replace(path)
            self.send_json({'ok': True, 'status': 'saved; not a verification of live Flow compatibility'})
        else:
            raise Problem('Route not found', 404)

    def handle_request(self):
        try:
            self.dispatch()
        except Problem as e:
            self.send_json({'error': str(e)}, e.status)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            return
        except (ValueError, TypeError, KeyError):
            self.send_json({'error': 'Invalid request data'}, 400)
        except Exception as e:
            self.send_json({'error': 'Server operation failed ('+type(e).__name__+')'}, 500)
    do_GET = handle_request
    do_POST = handle_request


def main():
    parser = argparse.ArgumentParser(prog='GenFlow')
    parser.add_argument('--init', action='store_true')
    args = parser.parse_args()
    store = Store(os.getenv('GENFLOW_DATA', '/data'))
    if args.init:
        import getpass
        Auth(store).bootstrap(getpass.getpass('New GenFlow password (16+ characters): '))
        print('GenFlow administrator initialized. Existing sessions revoked.')
        return
    Server(('0.0.0.0', int(os.getenv('PORT', '8080'))), store).serve_forever()


if __name__ == '__main__':
    main()
