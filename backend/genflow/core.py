import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Blocked(Problem):
    def __init__(self, message):
        super().__init__(message, 409)


class Cancelled(Exception):
    pass


def uid():
    return secrets.token_hex(16)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.media = self.root / 'media'
        self.media.mkdir(exist_ok=True, mode=0o700)
        self.db = self.root / 'genflow.sqlite3'
        with self.connect() as c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    characters TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    command TEXT NOT NULL, script TEXT NOT NULL, plan TEXT, settings TEXT NOT NULL,
                    state TEXT NOT NULL, cancel INTEGER NOT NULL DEFAULT 0, error TEXT,
                    output TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS shots(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                    position INTEGER NOT NULL, spec TEXT NOT NULL, state TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0, prompt TEXT, path TEXT, qa TEXT,
                    UNIQUE(job_id,position));
                CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, shot_id TEXT NOT NULL REFERENCES shots(id),
                    number INTEGER NOT NULL, state TEXT NOT NULL, prompt TEXT NOT NULL,
                    started REAL NOT NULL, finished REAL, error TEXT, qa TEXT, path TEXT);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at REAL NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id));
                CREATE INDEX IF NOT EXISTS job_state ON jobs(state,created);
                CREATE INDEX IF NOT EXISTS event_job ON events(job_id,seq);
            ''')
            c.execute("INSERT OR IGNORE INTO meta VALUES('schema','1')")
        os.chmod(self.db, 0o600)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def rows(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        if not rows:
            raise Problem('Record not found', 404)
        return rows[0]

    def execute(self, sql, args=()):
        with self.connect() as c:
            c.execute(sql, args)

    def event(self, job, kind, message):
        with self.connect() as c:
            c.execute('INSERT INTO events(job_id,at,kind,message) VALUES(?,?,?,?)',
                      (job, time.time(), kind, message[:3000]))
            c.execute('UPDATE jobs SET updated=? WHERE id=?', (time.time(), job))

    def check_cancel(self, job):
        if self.one('SELECT cancel FROM jobs WHERE id=?', (job,))['cancel']:
            raise Cancelled()

    def set_state(self, job, state, error=None):
        self.execute('UPDATE jobs SET state=?,error=?,updated=? WHERE id=?',
                     (state, error, time.time(), job))
        self.event(job, state, error or state)

    def recover(self):
        # Single worker holds an OS file lock. Do this only after taking that lock.
        for job in self.rows("SELECT id,cancel FROM jobs WHERE state='running'"):
            if job['cancel']:
                self.set_state(job['id'], 'cancelled')
                continue
            uncertain = self.rows("SELECT id FROM shots WHERE job_id=? AND state='submitting'", (job['id'],))
            self.set_state(job['id'], 'blocked' if uncertain else 'queued',
                           'Submission outcome unknown. Reconcile the Flow project; upload the matching clip or explicitly retry.' if uncertain else None)

    def claim(self):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM jobs WHERE state='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            c.execute("UPDATE jobs SET state='running',updated=? WHERE id=?", (time.time(), row['id']))
            return dict(row)

    def project(self, data):
        title = str(data.get('title', '')).strip()
        chars = data.get('characters', [])
        if not title or len(title) > 120 or not isinstance(chars, list) or len(chars) > 30:
            raise Problem('Title (1–120 characters) and a character array (max 30) required')
        for char in chars:
            if not isinstance(char, dict) or not char.get('name') or not char.get('identity'):
                raise Problem('Every character needs name and identity')
            if len(encoded(char)) > 16000:
                raise Problem('Character description too long')
        if len({str(x['name']).casefold() for x in chars}) != len(chars):
            raise Problem('Character names must be unique')
        key = uid()
        self.execute('INSERT INTO projects VALUES(?,?,?,?)', (key, title, encoded(chars), time.time()))
        return self.one('SELECT * FROM projects WHERE id=?', (key,))

    def create_job(self, data):
        project = self.one('SELECT * FROM projects WHERE id=?', (data.get('project_id'),))
        command = str(data.get('command', '')).strip()
        script = str(data.get('script', '')).strip()
        if not command or len(command) > 4000 or len(script) > 100000:
            raise Problem('Command required (max 4000); script max 100000 characters')
        raw = data.get('settings', {})
        if not isinstance(raw, dict):
            raise Problem('Settings must be an object')
        settings = {'max_attempts': int(raw.get('max_attempts', 3)),
                    'max_generations': int(raw.get('max_generations', 60)),
                    'aspect': raw.get('aspect', '16:9'), 'require_audio': bool(raw.get('require_audio', True))}
        if not 1 <= settings['max_attempts'] <= 5 or not 1 <= settings['max_generations'] <= 300:
            raise Problem('Attempts 1–5; total generation budget 1–300')
        if settings['aspect'] not in ('16:9', '9:16'):
            raise Problem('Aspect must be 16:9 or 9:16')
        request_id = data.get('client_request_id')
        if request_id is not None and (not isinstance(request_id, str) or not 8 <= len(request_id) <= 80):
            raise Problem('Invalid client request ID')
        fingerprint = hashlib.sha256(encoded({'project_id': project['id'], 'command': command, 'script': script, 'settings': settings}).encode()).hexdigest()
        key, now = uid(), time.time()
        # Character bible is snapshotted, so later project edits cannot silently change continuity.
        settings['characters'] = json.loads(project['characters'])
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone() if request_id else None
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise Problem('Client request ID was already used for different inputs', 409)
                key = existing['job_id']
            else:
                c.execute('''INSERT INTO jobs(id,project_id,command,script,settings,state,created,updated)
                             VALUES(?,?,?,?,?,'queued',?,?)''', (key, project['id'], command, script, encoded(settings), now, now))
                if request_id:
                    c.execute('INSERT INTO requests VALUES(?,?,?)', (request_id, fingerprint, key))
        self.event(key, 'queued', 'Episode queued')
        return self.job(key)

    def job(self, key):
        job = self.one('SELECT * FROM jobs WHERE id=?', (key,))
        for field in ('settings', 'plan'):
            job[field] = json.loads(job[field]) if job[field] else None
        job['shots'] = self.rows('SELECT * FROM shots WHERE job_id=? ORDER BY position', (key,))
        for shot in job['shots']:
            for field in ('spec', 'qa'):
                shot[field] = json.loads(shot[field]) if shot[field] else None
            shot['attempts'] = self.rows('SELECT * FROM attempts WHERE shot_id=? ORDER BY number', (shot['id'],))
        job['events'] = self.rows('SELECT * FROM events WHERE job_id=? ORDER BY seq DESC LIMIT 200', (key,))[::-1]
        return job


class Auth:
    def __init__(self, store):
        self.store = store
        self.failures = {}

    def bootstrap(self, password):
        if len(password) < 16:
            raise ValueError('Admin password must contain at least 16 characters')
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
        # Explicit operator action only; not read from a default committed password.
        self.store.execute("INSERT OR REPLACE INTO meta VALUES('password',?)", (salt.hex()+':'+digest,))
        self.store.execute('DELETE FROM sessions')

    def login(self, password, source):
        now = time.time()
        hits = [x for x in self.failures.get(source, []) if x > now-300]
        if len(hits) >= 5:
            raise Problem('Too many attempts. Wait 5 minutes.', 429)
        self.failures[source] = hits + [now]
        rows = self.store.rows("SELECT value FROM meta WHERE key='password'")
        if not rows:
            raise Problem('Administrator has not initialized GenFlow', 503)
        salt, expected = rows[0]['value'].split(':')
        actual = hashlib.scrypt(str(password).encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        if not hmac.compare_digest(actual, expected):
            raise Problem('Invalid credentials', 401)
        self.failures.pop(source, None)
        token = secrets.token_urlsafe(48)
        self.store.execute('DELETE FROM sessions WHERE expires<?', (now,))
        self.store.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), now+7*86400))
        return {'token': token, 'expires': now+7*86400}

    def require(self, header):
        token = header.removeprefix('Bearer ')
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not header.startswith('Bearer ') or not self.store.rows('SELECT hash FROM sessions WHERE hash=? AND expires>?', (digest, time.time())):
            raise Problem('Sign in required', 401)
        return digest
