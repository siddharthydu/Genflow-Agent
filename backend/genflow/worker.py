import fcntl
import json
import os
from pathlib import Path
import signal
import time
from .ai import Intelligence, make_prompt
from .core import Store, Blocked, Cancelled, Problem, encoded, uid
from .flow import FlowBrowser
from .media import technical_qa, assemble


class Worker:
    def __init__(self, store, ai=None, flow=None):
        self.store = store
        self.ai = ai or Intelligence()
        self.flow = flow or FlowBrowser(store)

    def references(self, job, spec):
        output = []
        for char in job['settings']['characters']:
            if char['name'] not in spec['characters']:
                continue
            # Names are not filesystem paths. Stored reference IDs are random server-generated IDs.
            key = char.get('reference_id', '')
            if len(key) == 32 and all(c in '0123456789abcdef' for c in key):
                path = self.store.media / (key+'.jpg')
                if path.exists():
                    output.append((path, 'image/jpeg', char['name']+' portrait'))
        return output

    def process(self, key):
        store = self.store
        cancel = lambda: store.check_cancel(key)
        try:
            cancel()
            job = store.job(key)
            if not job['plan']:
                store.event(key, 'planning', 'Planning scenes and shots with locked characters')
                history = store.rows("SELECT command,plan FROM jobs WHERE project_id=? AND id<>? AND plan IS NOT NULL ORDER BY created DESC LIMIT 3",
                                     (job['project_id'], key))
                job['history'] = [{'command': item['command'], 'plan': json.loads(item['plan'])} for item in reversed(history)]
                plan = self.ai.plan(job)
                cancel()
                if not job['settings']['characters'] and plan.get('characters'):
                    job['settings']['characters'] = plan['characters']
                with store.connect() as c:
                    c.execute('UPDATE jobs SET plan=?,settings=? WHERE id=?', (encoded(plan), encoded(job['settings']), key))
                    c.execute("UPDATE projects SET characters=? WHERE id=? AND characters='[]'",
                              (encoded(job['settings']['characters']), job['project_id']))
                    for i, shot in enumerate(plan['shots']):
                        c.execute("INSERT INTO shots(id,job_id,position,spec,state) VALUES(?,?,?,?,'pending')",
                                  (uid(), key, i, encoded(shot)))
                job = store.job(key)
            previous = None
            for shot in job['shots']:
                cancel()
                if shot['state'] == 'approved':
                    previous = self.store.media / shot['path']
                    continue
                if shot['state'] == 'submitting':
                    raise Blocked('Unresolved Flow submission. Import its clip or explicitly acknowledge resubmission risk.')
                if shot['state'] == 'review':
                    raise Blocked('Shot '+str(shot['position']+1)+' needs human review of uncertain QA checks.')
                previous = self.process_shot(job, shot, previous, cancel)
            cancel()
            shots = store.job(key)['shots']
            if not shots or any(s['state'] != 'approved' for s in shots):
                raise Blocked('Export requires approval for every shot')
            store.event(key, 'exporting', 'Normalizing tracks and assembling approved clips in order')
            folder = store.media / key
            output = assemble([store.media/s['path'] for s in shots], folder/'episode.mp4', job['settings']['aspect'], cancel)
            store.execute('UPDATE jobs SET output=? WHERE id=?', (str(output.relative_to(store.media)), key))
            cancel()
            store.set_state(key, 'completed')
        except Cancelled:
            store.set_state(key, 'cancelled', 'Cancelled. A generation already submitted to Flow may still consume Google credits.')
        except Blocked as e:
            store.set_state(key, 'blocked', str(e))
        except Exception as e:
            # Avoid leaking API credentials from exception messages or browser profiles into logs.
            store.set_state(key, 'failed', 'Operation failed ('+type(e).__name__+'). Review diagnostics and resume.')

    def process_shot(self, job, shot, previous, cancel):
        store, settings, spec, key = self.store, job['settings'], shot['spec'], job['id']
        refs = self.references(job, spec)
        feedback = (shot['qa'] or {}).get('issues')
        while True:
            cancel()
            shot = store.job(key)['shots'][shot['position']]
            path = store.media/shot['path'] if shot['path'] else None
            if shot['state'] in ('downloaded', 'uploaded', 'analyzing') and path and path.exists():
                pass
            else:
                if shot['attempt'] >= settings['max_attempts']:
                    raise Blocked('Shot retry limit reached. Review attempts; no additional credits spent.')
                total = store.one('SELECT COUNT(*) AS n FROM attempts a JOIN shots s ON a.shot_id=s.id WHERE s.job_id=?', (key,))['n']
                if total >= settings['max_generations']:
                    raise Blocked('Episode generation budget reached.')
                # Configuration/login checks happen before reserving an attempt.
                if isinstance(self.flow, FlowBrowser):
                    self.flow.load_config()
                prompt = make_prompt(spec, settings, feedback)
                number, attempt = shot['attempt']+1, uid()
                path = store.media / key / (shot['id']+'-'+str(number)+'.mp4')
                path.parent.mkdir(exist_ok=True, parents=True)
                def on_submit():
                    cancel()
                    with store.connect() as c:
                        c.execute("INSERT INTO attempts(id,shot_id,number,state,prompt,started) VALUES(?,?,?,'submitting',?,?)",
                                  (attempt, shot['id'], number, prompt, time.time()))
                        c.execute("UPDATE shots SET state='submitting',attempt=?,prompt=?,path=NULL,qa=NULL WHERE id=?",
                                  (number, prompt, shot['id']))
                    store.event(key, 'generating', 'Submitting shot '+str(shot['position']+1)+', attempt '+str(number))
                self.flow.generate(prompt, path, [r[0] for r in refs], cancel, on_submit)
                shot = store.one('SELECT * FROM shots WHERE id=?', (shot['id'],))
                rel = str(path.relative_to(store.media))
                with store.connect() as c:
                    c.execute("UPDATE shots SET state='downloaded',path=? WHERE id=?", (rel, shot['id']))
                    c.execute("UPDATE attempts SET state='downloaded',path=? WHERE id=?", (rel, attempt))
            cancel()
            store.execute("UPDATE shots SET state='analyzing' WHERE id=?", (shot['id'],))
            store.event(key, 'qa', 'Checking shot '+str(shot['position']+1))
            try:
                technical = technical_qa(path, spec, settings, cancel)
            except Problem as e:
                if e.status != 422:
                    raise
                technical = {'approved': False, 'issues': ['Clip could not be fully decoded or analyzed'], 'method': 'FFmpeg decode failure'}
            if technical['approved']:
                context = list(refs)
                if previous:
                    context.append((previous, 'video/mp4', 'previous accepted shot: continuity and voice reference'))
                semantic = self.ai.inspect(path, spec, settings['characters'], context)
            else:
                semantic = {'approved': False, 'checks': {}, 'issues': []}
            issues = technical['issues'] + semantic.get('issues', [])
            qa = {'approved': technical['approved'] and semantic['approved'], 'technical': technical,
                  'semantic': semantic, 'issues': issues}
            uncertain = technical['approved'] and any(v == 'uncertain' for v in semantic.get('checks', {}).values())
            state = 'approved' if qa['approved'] else ('review' if uncertain else 'rejected')
            with store.connect() as c:
                c.execute('UPDATE shots SET state=?,qa=? WHERE id=?', (state, encoded(qa), shot['id']))
                c.execute('UPDATE attempts SET state=?,qa=?,finished=? WHERE shot_id=? AND number=?',
                          (state, encoded(qa), time.time(), shot['id'], shot['attempt']))
            cancel()
            if state == 'approved':
                return path
            if state == 'review':
                raise Blocked('QA uncertain. Play the clip and review identity, dialogue, voice and lip sync before approval.')
            feedback = issues
            # Preserve rejected clip and attempt QA; next iteration creates an independent new attempt.
            store.event(key, 'retry', 'Shot rejected; prompt feedback recorded')


def main():
    store = Store(os.getenv('GENFLOW_DATA', '/data'))
    with open(store.root/'worker.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A GenFlow worker is already active')
        store.recover()
        worker = Worker(store)
        stop = False
        def shutdown(*_):
            nonlocal stop
            stop = True
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            while not stop:
                job = store.claim()
                if job:
                    worker.process(job['id'])
                else:
                    time.sleep(1)
        finally:
            worker.flow.close()


if __name__ == '__main__':
    main()
