"""Synthetic fixtures are exclusively test media, never presented as Google Flow generations."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from genflow.core import Auth, Blocked, Cancelled, Problem, Store, encoded
from genflow.ai import Intelligence, audit_dialogue, make_prompt, validate_plan
from genflow.flow import validate_config
from genflow.media import technical_qa, assemble, probe, run
from genflow.server import Server
from genflow.worker import Worker


def spec(dialogue='Hello', characters=None):
    return {'scene': 1, 'visual': 'Person speaks calmly', 'dialogue': dialogue, 'speaker': 'Avi' if dialogue else '',
            'characters': ['Avi'] if characters is None else characters,
            'wardrobe': {'Avi': 'blue shirt'}, 'duration': 4, 'location': 'home', 'requirements': ['static camera']}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.project = self.store.project({'title': 'Test project', 'characters': [{'name': 'Avi', 'identity': 'Adult Indian man', 'voice': 'Indian male'}]})
    def tearDown(self):
        self.temp.cleanup()
    def job(self, **kwargs):
        return self.store.create_job({'project_id': self.project['id'], 'command': 'Create episode', **kwargs})


class CoreTests(Base):
    def test_job_creation_is_idempotent_and_detects_conflicts(self):
        first = self.job(client_request_id='a-stable-device-request')
        second = self.job(client_request_id='a-stable-device-request')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.store.rows('SELECT id FROM jobs')), 1)
        with self.assertRaises(Problem): self.job(client_request_id='a-stable-device-request', script='different script')
    def test_ordered_dialogue_audit(self):
        shot = spec('Main kal aaunga.')
        result = audit_dialogue('Avi: Main kal aaunga.', [shot], [{'name':'Avi'}])
        self.assertTrue(result['exact_dialogue_verified'])
        shot['dialogue'] = 'Main nahi aaunga.'
        with self.assertRaises(Blocked): audit_dialogue('Avi: Main kal aaunga.', [shot], [{'name':'Avi'}])
        self.assertFalse(audit_dialogue('Unstructured prose', [shot], [{'name':'Avi'}])['exact_dialogue_verified'])
    def test_qa_rejects_incomplete_model_checks(self):
        ai = Intelligence()
        ai.call = lambda *args: {'checks': {'dialogue':'pass'}}
        with self.assertRaises(Blocked): ai.inspect(Path('unused'), spec(), [])
    def test_missing_api_config_blocks_without_network(self):
        ai = Intelligence(); ai.key=''; ai.model=''
        with self.assertRaises(Blocked): ai.call('hello')
    def test_character_snapshot_is_immutable(self):
        job = self.job()
        self.store.execute('UPDATE projects SET characters=?', ('[]',))
        self.assertEqual(job['settings']['characters'][0]['name'], 'Avi')
        self.assertEqual(self.store.job(job['id'])['settings']['characters'][0]['name'], 'Avi')
    def test_password_and_session_expiry(self):
        auth = Auth(self.store)
        with self.assertRaises(ValueError): auth.bootstrap('short')
        auth.bootstrap('long-GenFlow-test-password')
        with self.assertRaises(Problem): auth.login('wrong', 'test')
        token = auth.login('long-GenFlow-test-password', 'test')['token']
        auth.require('Bearer '+token)
        self.assertFalse(self.store.rows('SELECT * FROM sessions WHERE hash=?', (token,)))
        self.store.execute('UPDATE sessions SET expires=0')
        with self.assertRaises(Problem): auth.require('Bearer '+token)
    def test_login_rate_limit(self):
        auth = Auth(self.store); auth.bootstrap('long-GenFlow-test-password')
        for _ in range(5):
            with self.assertRaises(Problem): auth.login('wrong','source')
        with self.assertRaises(Problem) as error: auth.login('long-GenFlow-test-password','source')
        self.assertEqual(error.exception.status,429)
    def test_settings_validation(self):
        for settings in ({'max_attempts':0},{'max_generations':301},{'aspect':'1:1'}):
            with self.assertRaises(Problem): self.job(settings=settings)
    def test_atomic_claim(self):
        job=self.job(); claimed=[]
        def claim(): claimed.append(self.store.claim())
        threads=[threading.Thread(target=claim) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(x is not None for x in claimed),1)
    def test_cancel_prevents_claim(self):
        job=self.job(); self.store.execute('UPDATE jobs SET cancel=1 WHERE id=?',(job['id'],))
        self.assertIsNone(self.store.claim())
        with self.assertRaises(Cancelled):self.store.check_cancel(job['id'])
    def test_recovery_blocks_unknown_submission(self):
        job=self.job();self.store.claim()
        self.store.execute("INSERT INTO shots(id,job_id,position,spec,state) VALUES('test',?,0,?,'submitting')",(job['id'],encoded(spec())))
        self.store.recover()
        self.assertEqual(self.store.job(job['id'])['state'],'blocked')
        self.assertIsNone(self.store.claim())
    def test_recovery_requeues_safe_work(self):
        job=self.job(); self.store.claim();self.store.recover()
        self.assertEqual(self.store.job(job['id'])['state'],'queued')
    def test_plan_rejects_unknown_identity_and_duration(self):
        shot=spec();validate_plan({'shots':[shot]},[{'name':'Avi'}])
        shot['characters']=['unknown']
        with self.assertRaises(Blocked):validate_plan({'shots':[shot]},[{'name':'Avi'}])
        shot=spec();shot['duration']=50
        with self.assertRaises(Blocked):validate_plan({'shots':[shot]},[])
    def test_prompt_keeps_exact_dialogue_and_bible(self):
        shot=spec('Main… kal… confident dikhna chahta hoon.')
        prompt=make_prompt(shot,self.job()['settings'],['mouth timing wrong'])
        self.assertIn(shot['dialogue'],prompt);self.assertIn('Adult Indian man',prompt);self.assertIn('mouth timing wrong',prompt)
    def test_flow_rejects_unapproved_origins(self):
        config={'project_url':'https://flow.google.com/project/1','prompt':'textarea','submit':'button','tile':'.tile','download':'.download'}
        validate_config(config)
        for url in ('https://flow.google.com.evil.test/','http://flow.google.com','https://user:secret@flow.google.com/','http://127.0.0.1'):
            with self.assertRaises(Blocked):validate_config(dict(config,project_url=url))


@unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
class MediaTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.fixtures=tempfile.TemporaryDirectory()
        cls.landscape=Path(cls.fixtures.name)/'landscape.mp4'
        cls.portrait=Path(cls.fixtures.name)/'portrait.mp4'
        cls.silent=Path(cls.fixtures.name)/'silent.mp4'
        for output,size,audio in ((cls.landscape,'640x360',True),(cls.portrait,'360x640',True),(cls.silent,'640x360',False)):
            args=['ffmpeg','-y','-v','error','-f','lavfi','-i',f'color=c=blue:s={size}:r=24:d=4']
            if audio:args+=['-f','lavfi','-i','sine=frequency=440:duration=4']
            args+=['-c:v','libx264','-pix_fmt','yuv420p','-threads','1']
            if audio:args+=['-c:a','aac','-shortest']
            subprocess.run(args+[str(output)],check=True)
    @classmethod
    def tearDownClass(cls):cls.fixtures.cleanup()
    def test_full_technical_qa(self):
        result=technical_qa(self.landscape,spec(),self.job()['settings'])
        self.assertTrue(result['approved'],result)
    def test_missing_audio_is_rejected(self):
        result=technical_qa(self.silent,spec(),self.job()['settings'])
        self.assertFalse(result['approved']);self.assertIn('Required audio track missing',result['issues'])
    def test_wrong_aspect_is_rejected(self):
        result=technical_qa(self.portrait,spec(),self.job()['settings'])
        self.assertFalse(result['approved'])
    def test_invalid_video_rejected(self):
        path=Path(self.temp.name)/'invalid.mp4';path.write_text('not a video')
        with self.assertRaises(Problem):technical_qa(path,spec(),self.job()['settings'])
    def test_export_normalizes_and_orders_tracks(self):
        output=assemble([self.landscape,self.silent],Path(self.temp.name)/'export/episode.mp4','16:9')
        data=probe(output);self.assertAlmostEqual(float(data['format']['duration']),8,delta=.3)
        self.assertEqual({s['codec_type'] for s in data['streams']},{'audio','video'})
        self.assertEqual(data['streams'][0]['width'],1280)
    def test_media_process_cancellation(self):
        def cancel():raise Cancelled()
        with self.assertRaises(Cancelled):run(['ffmpeg','-re','-f','lavfi','-i','sine=duration=30','-f','null','-'],cancel)
    def test_worker_completed_pipeline_with_test_doubles(self):
        class TestAI:
            def plan(self,job):return {'title':'test','shots':[spec(),spec()]}
            def inspect(self,*args):return {'approved':True,'checks':{'dialogue':'pass'},'issues':[]}
        source=self.landscape
        class TestFlow:
            def generate(self,prompt,path,refs,cancel,on_submit):on_submit();shutil.copyfile(source,path);return path
        job=self.job();self.store.claim();Worker(self.store,TestAI(),TestFlow()).process(job['id'])
        result=self.store.job(job['id']);self.assertEqual(result['state'],'completed',result.get('error'))
        self.assertTrue((self.store.media/result['output']).exists());self.assertEqual(len(result['shots']),2)
        self.assertTrue(all(x['state']=='approved' for x in result['shots']))
        self.assertTrue(all(x['attempts'][0]['state']=='approved' and x['attempts'][0]['finished'] for x in result['shots']))
    def test_worker_retry_budget_and_feedback(self):
        class TestAI:
            calls=0
            def plan(self,job):return {'shots':[spec()]}
            def inspect(self,*args):
                self.calls+=1
                return {'approved':False,'checks':{'dialogue':'fail'},'issues':['wrong words']}
        prompts=[];source=self.landscape
        class TestFlow:
            def generate(self,prompt,path,refs,cancel,on_submit):prompts.append(prompt);on_submit();shutil.copyfile(source,path)
        job=self.job(settings={'max_attempts':2});self.store.claim();Worker(self.store,TestAI(),TestFlow()).process(job['id'])
        result=self.store.job(job['id']);self.assertEqual(result['state'],'blocked');self.assertEqual(result['shots'][0]['attempt'],2)
        self.assertEqual(len(prompts),2);self.assertIn('wrong words',prompts[1])
    def test_ambiguous_generation_is_not_automatically_repeated(self):
        class TestAI:
            def plan(self,job):return {'shots':[spec()]}
        class TestFlow:
            calls=0
            def generate(self,prompt,path,refs,cancel,on_submit):self.calls+=1;on_submit();raise Blocked('timed out')
        flow=TestFlow();job=self.job();self.store.claim();worker=Worker(self.store,TestAI(),flow);worker.process(job['id'])
        self.assertEqual(self.store.job(job['id'])['shots'][0]['state'],'submitting')
        worker.process(job['id']);self.assertEqual(flow.calls,1)
    def test_semantic_uncertainty_blocks_for_human_review(self):
        class TestAI:
            def plan(self,job):return {'shots':[spec()]}
            def inspect(self,*args):return {'approved':False,'checks':{'character_identity':'uncertain'},'issues':['no voice reference']}
        source=self.landscape
        class TestFlow:
            def generate(self,prompt,path,refs,cancel,on_submit):on_submit();shutil.copyfile(source,path)
        job=self.job();self.store.claim();Worker(self.store,TestAI(),TestFlow()).process(job['id'])
        result=self.store.job(job['id']);self.assertEqual(result['state'],'blocked');self.assertEqual(result['shots'][0]['state'],'review')


class HTTPTests(Base):
    def setUp(self):
        super().setUp();Auth(self.store).bootstrap('long-GenFlow-test-password')
        self.server=Server(('127.0.0.1',0),self.store);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.token=Auth(self.store).login('long-GenFlow-test-password','local')['token']
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();super().tearDown()
    def request(self,path,body=None,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+self.token
        req=urllib.request.Request(self.origin+path,None if body is None else encoded(body).encode(),headers)
        try:
            with urllib.request.urlopen(req,timeout=10) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_append_reusable_character_and_reject_duplicate(self):
        route='/api/projects/'+self.project['id']+'/characters'
        body={'name':'Ruhi','identity':'Adult Indian woman','voice':'Indian female'}
        self.assertEqual(self.request(route,body)[0],201)
        self.assertEqual(self.request(route,body)[0],400)
    def test_health_and_auth(self):
        self.assertEqual(self.request('/health',token=False)[0],200)
        self.assertEqual(self.request('/api/jobs',token=False)[0],401)
        self.assertEqual(self.request('/api/jobs')[0],200)
    def test_create_poll_cancel_resume(self):
        status,job=self.request('/api/jobs',{'project_id':self.project['id'],'command':'Episode 05'})
        self.assertEqual(status,201);key=job['id']
        self.assertEqual(self.request('/api/jobs/'+key)[1]['state'],'queued')
        self.assertEqual(self.request('/api/jobs/'+key+'/cancel',{})[0],200)
        self.assertEqual(self.request('/api/jobs/'+key)[1]['state'],'cancelled')
        self.assertEqual(self.request('/api/jobs/'+key+'/resume',{})[0],200)
        self.assertEqual(self.request('/api/jobs/'+key)[1]['state'],'queued')
    def test_no_export_before_completion(self):
        job=self.job();self.assertEqual(self.request('/api/jobs/'+job['id']+'/export')[0],409)
    def test_flow_config_does_not_accept_secrets(self):
        config={'project_url':'https://flow.google.com/','prompt':'x','submit':'x','tile':'x','download':'x','cookie':'secret'}
        self.assertEqual(self.request('/api/config/flow',config)[0],400)
    def test_review_cannot_bypass_technical_qa(self):
        job=self.job()
        self.store.set_state(job['id'],'blocked')
        shot_id='a'*32
        self.store.execute("INSERT INTO shots(id,job_id,position,spec,state,qa) VALUES(?,?,0,?,'review',?)",
                           (shot_id,job['id'],encoded(spec()),encoded({'technical':{'approved':False}})))
        self.assertEqual(self.request('/api/shots/'+shot_id+'/approve',{'note':'I watched the clip carefully'})[0],409)
    def test_export_byte_ranges_are_authenticated(self):
        job=self.job();folder=self.store.media/job['id'];folder.mkdir();path=folder/'episode.mp4';path.write_bytes(b'0123456789')
        self.store.execute("UPDATE jobs SET state='completed',output=? WHERE id=?",(str(path.relative_to(self.store.media)),job['id']))
        request=urllib.request.Request(self.origin+'/api/jobs/'+job['id']+'/export',headers={'Authorization':'Bearer '+self.token,'Range':'bytes=2-5'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345');self.assertEqual(response.headers['Content-Range'],'bytes 2-5/10')
    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_upload_reconcile_analyze_and_record_human_review(self):
        job=self.job();key=job['id'];shot_id='b'*32
        self.store.set_state(key,'blocked')
        self.store.execute("INSERT INTO shots(id,job_id,position,spec,state) VALUES(?,?,0,?,'submitting')",(shot_id,key,encoded(spec())))
        source=Path(self.temp.name)/'synthetic-import.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=green:s=640x360:r=24:d=4',
                        '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-threads','1','-c:a','aac','-shortest',str(source)],check=True)
        req=urllib.request.Request(self.origin+'/api/shots/'+shot_id+'/clip',source.read_bytes(),
                                   {'Authorization':'Bearer '+self.token,'Content-Type':'video/mp4'})
        with urllib.request.urlopen(req) as response:self.assertEqual(response.status,200)
        self.assertEqual(self.store.job(key)['shots'][0]['state'],'uploaded')
        class TestAI:
            def inspect(self,*args):return {'approved':False,'checks':{'voice':'uncertain'},'issues':['first voice clip']}
        class NoGenerate:
            def generate(self,*args):raise AssertionError('Reconciled clip must not be generated again')
        # Store a valid plan so the imported shot resumes at QA.
        self.store.execute('UPDATE jobs SET plan=? WHERE id=?',(encoded({'shots':[spec()]}),key))
        Worker(self.store,TestAI(),NoGenerate()).process(key)
        self.assertEqual(self.store.job(key)['shots'][0]['state'],'review')
        status,_=self.request('/api/shots/'+shot_id+'/approve',{'note':'Synthetic test review, not a real human quality claim'})
        self.assertEqual(status,200)
        result=self.store.job(key)['shots'][0]
        self.assertTrue(result['qa']['human_review']);self.assertEqual(result['state'],'approved')
    def test_bad_json_and_unknown_route(self):
        self.assertEqual(self.request('/api/projects',{'title':''})[0],400)
        self.assertEqual(self.request('/unknown')[0],404)
    def test_logout_revokes_session(self):
        self.assertEqual(self.request('/api/logout',{})[0],200)
        self.assertEqual(self.request('/api/jobs')[0],401)


if __name__=='__main__':unittest.main(verbosity=2)
