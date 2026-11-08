import datetime as dt,json,signal,sqlite3,sys,tempfile,unittest
from pathlib import Path
import server
from unittest.mock import patch
class InboxTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=server.DB;server.DB=Path(self.tmp.name)/'test.sqlite';server.init_db()
  config=Path(self.tmp.name)/'sources.json'
  config.write_text(json.dumps(dict(server.app_settings.DEFAULTS,retrieval_python=sys.executable)))
  self.source_patch=patch.object(server.app_settings,'SOURCES_FILE',config);self.source_patch.start()
  self.old_status=dict(server.STATUS)
  server.STATUS.update(updating=False,last_update='',warnings=[],message='')
 def tearDown(self):
  self.source_patch.stop();server.DB=self.old;server.STATUS.clear();server.STATUS.update(self.old_status);self.tmp.cleanup()
 def test_read_persists_and_is_not_negative_feedback(self):
  p={'id':'p','title':'test','url':'https://example.org/p','source':'test','score':7.1,'discovered':'2026-10-30','published':'2026-10-29'}
  with server.connect() as c:c.execute('INSERT INTO papers(id,data,day) VALUES(?,?,?)',('p',json.dumps(p),'2026-10-30'))
  server.action('p','read');x=server.snapshot()['papers'][0]
  self.assertTrue(x['read']);self.assertFalse(x['favorite']);self.assertEqual(x['score'],7.1)
  server.action('p','unread');self.assertFalse(server.snapshot()['papers'][0]['read'])
 def test_bulk_read_is_scoped_idempotent_and_keeps_favorites(self):
  with server.connect() as c:
   for pid in ('a','b','outside'):
    c.execute('INSERT INTO papers(id,data,day,favorite) VALUES(?,?,?,1)',(pid,json.dumps({'id':pid}),'2026-11-07'))
  server.mark_read_many(['a','b','a','missing']);server.mark_read_many(['a','b'])
  with server.connect() as c:
   self.assertEqual([tuple(r) for r in c.execute('SELECT id,read,favorite FROM papers ORDER BY id')],[('a',1,1),('b',1,1),('outside',0,1)])
   self.assertEqual(c.execute('SELECT count(*) FROM reading_requests_v3').fetchone()[0],0)
  with self.assertRaises(ValueError):server.mark_read_many('all')
 def test_favorite_is_local_only(self):
  p={'id':'p','title':'test','url':'https://example.org/p','source':'test','score':7.1,'discovered':'2026-10-30','published':'2026-10-29'}
  with server.connect() as c:c.execute('INSERT INTO papers(id,data,day) VALUES(?,?,?)',('p',json.dumps(p),'2026-10-30'))
  with patch.object(server,'urlopen',side_effect=AssertionError('network forbidden')), patch.object(server.subprocess,'Popen',side_effect=AssertionError('task forbidden')), patch.object(server.threading,'Thread',side_effect=AssertionError('background action forbidden')):
   server.action('p','favorite')
   x=server.snapshot()['papers'][0];self.assertTrue(x['favorite']);self.assertFalse(x['read']);self.assertEqual(x['zotero_status'],'')
   server.action('p','unfavorite');self.assertFalse(server.snapshot()['papers'][0]['favorite'])
 def test_failed_empty_snapshot_is_not_success(self):
  path=Path(self.tmp.name)/'failed.json'
  path.write_text(json.dumps({'schedule_date_shanghai':'2026-11-08','papers':[],'status':'partial','warnings':['SSL failure']}))
  with self.assertRaises(RuntimeError):server.ingest(path)
  self.assertEqual(server.STATUS['last_update'],'')
  self.assertFalse(server.failed_empty_snapshot({'papers':[],'status':'complete','warnings':[]}))
 def test_openai_summary_route_uses_selected_model_and_effort(self):
  with patch.object(server.app_settings,'get_settings',return_value={'summary_provider':'openai','summary_model':'gpt-6.1-sol','summary_effort':'medium'}),patch('summary_api.ensure_summaries') as api,patch.object(server,'complete_bilingual_summaries',side_effect=AssertionError('Codex not used for API summaries')):
   papers=[{'id':'a'}];server.summarize(papers,'2026-11-08')
   api.assert_called_once_with(papers,'2026-11-08',server.CACHE,'gpt-6.1-sol','medium')
 def test_summary_sentence_limit(self):
  server.validate_summary('问题：第一句。\n\n方法：第一句。第二句。\n\n结果：第一句。第二句。第三句。')
  with self.assertRaises(ValueError):server.validate_summary('问题：一。二。三。四。\n方法：一。\n结果：一。')
  with self.assertRaises(ValueError):server.validate_summary('问题：一。\n方法：一。')
 def test_publication_day_then_relevance(self):
  values=[('older','2026-11-02',9.9),('early','2026-11-03T01:00:00Z',8.5),('late','2026-11-03T23:00:00Z',7.1),('missing','',10)]
  with server.connect() as c:
   for pid,date,score in values:c.execute('INSERT INTO papers(id,data,day) VALUES(?,?,?)',(pid,json.dumps({'id':pid,'published':date,'score':score}),'2026-11-05'))
  self.assertEqual([p['id'] for p in server.snapshot()['papers']],['early','late','older','missing'])
 def test_invalid_action_rejected(self):
  with self.assertRaises(ValueError):server.action('p','delete_zotero')
 def test_ingest_independent_snapshot_preserves_state(self):
  path=Path(self.tmp.name)/'candidates.json'
  data={'schedule_date_shanghai':'2026-10-30','papers':[{'url':f'https://example.org/{i}','title':str(i),'score':i,'abstract':'Original abstract'} for i in range(12)]}
  path.write_text(json.dumps(data))
  with patch.object(server,'summarize'),patch.object(server,'enrich',side_effect=lambda p:p):
   server.ingest(path)
   papers=server.snapshot()['papers'];self.assertEqual(len(papers),10)
   self.assertEqual({p['score'] for p in papers},set(range(2,12)))
   pid=papers[0]['id'];server.action(pid,'favorite');server.action(pid,'read')
   server.ingest(path)
  p=next(p for p in server.snapshot()['papers'] if p['id']==pid)
  self.assertTrue(p['favorite']);self.assertTrue(p['read'])
 def test_connections_are_closed_after_transaction(self):
  with server.connect() as c:c.execute('SELECT 1')
  with self.assertRaises(sqlite3.ProgrammingError):c.execute('SELECT 1')
 def test_bootstrap_starts_scheduler_with_missing_or_corrupt_cache(self):
  with patch.object(server,'scheduler') as schedule:
   server.bootstrap();schedule.assert_called_once()
  with patch.object(server,'ingest',side_effect=ValueError('bad cache')),patch.object(server,'scheduler') as schedule:
   server.bootstrap(Path(self.tmp.name)/'bad.json')
   schedule.assert_called_once();self.assertFalse(server.STATUS['updating'])
   self.assertIn('bad cache',server.STATUS['message'])
 def run_scheduler_ticks(self,moments,ticks,update):
  with patch.object(server.dt,'datetime') as clock,patch.object(server.time,'monotonic',side_effect=ticks),patch.object(server,'run_update',side_effect=update) as run,patch.object(server.time,'sleep',side_effect=[None]*(len(moments)-1)+[StopIteration]):
   clock.now.side_effect=moments
   with self.assertRaises(StopIteration):server.scheduler()
  return run
 def test_scheduler_first_launch_before_six_then_next_day_after_six(self):
  moments=[dt.datetime(2026,10,30,2,tzinfo=server.TZ),dt.datetime(2026,10,31,5,59,tzinfo=server.TZ),dt.datetime(2026,10,31,6,tzinfo=server.TZ),dt.datetime(2026,10,31,6,1,tzinfo=server.TZ)]
  days=iter(['2026-10-30','2026-10-31'])
  def complete():server.STATUS['last_update']=next(days)
  run=self.run_scheduler_ticks(moments,[0,100000,100060,100120],complete)
  self.assertEqual(run.call_count,2)
 def test_scheduler_retries_failed_first_launch_before_six_after_thirty_minutes(self):
  moments=[dt.datetime(2026,10,30,2,tzinfo=server.TZ)]*4
  def update():
   if run_count[0]:server.STATUS['last_update']='2026-10-30'
   run_count[0]+=1
  run_count=[0]
  run=self.run_scheduler_ticks(moments,[0,1799,1800,3600],update)
  self.assertEqual(run.call_count,2)
 def test_scheduler_does_not_overlap_active_update(self):
  server.STATUS['updating']=True
  run=self.run_scheduler_ticks([dt.datetime(2026,10,30,7,tzinfo=server.TZ)],[0],lambda:None)
  run.assert_not_called()
 def test_timed_out_retrieval_is_stopped_and_reaped(self):
  with patch.object(server,'CACHE',Path(self.tmp.name)),patch('fulltext.load_config',return_value={}),patch.object(server.subprocess,'Popen') as spawn,patch.object(server.time,'monotonic',side_effect=[0,1801]),patch.object(server.os,'killpg') as kill:
   proc=spawn.return_value;proc.pid=12345;proc.poll.return_value=None
   proc.wait.side_effect=[server.subprocess.TimeoutExpired('retrieval',10),0]
   server.run_update()
  self.assertEqual(kill.call_args_list[0].args,(12345,signal.SIGTERM))
  self.assertEqual(kill.call_args_list[1].args,(12345,signal.SIGKILL))
  self.assertEqual(proc.wait.call_count,2)
  self.assertFalse(server.STATUS['updating']);self.assertEqual(server.STATUS['last_update'],'')
  self.assertIn('30分钟',server.STATUS['message'])
 def test_summary_failure_preserves_papers_and_retries_same_candidates(self):
  root=Path(self.tmp.name);path=root/'runs'/'2026'/'10'/'30'/'candidates-v2.json';path.parent.mkdir(parents=True)
  path.write_text(json.dumps({'schedule_date_shanghai':'2026-10-30','papers':[{'url':'https://example.org/p','title':'paper','score':9,'abstract':'Original abstract'}]}))
  def complete(papers,day):
   for p in papers:
    p['summary']='问题：一。\n方法：一。\n结果：一。'
  with patch.object(server,'CACHE',root),patch.object(server,'today',return_value='2026-10-30'),patch.object(server,'enrich',side_effect=lambda p:p),patch.object(server.subprocess,'Popen',side_effect=AssertionError('cached retrieval should be reused')):
   with patch.object(server,'summarize',side_effect=RuntimeError('temporary failure')):server.run_update()
   state=server.snapshot();self.assertEqual(len(state['papers']),1)
   self.assertEqual(state['status']['last_update'],'');self.assertFalse(state['status']['updating'])
   self.assertIn('自动重试',state['status']['message'])
   pid=state['papers'][0]['id'];server.action(pid,'favorite');server.action(pid,'read')
   with patch.object(server,'summarize',side_effect=complete):server.run_update()
  state=server.snapshot();self.assertEqual(state['status']['last_update'],'2026-10-30')
  self.assertEqual(json.loads((root/'update-completion.json').read_text())['last_update_at'],state['status']['last_update_at'])
  self.assertTrue(state['status']['last_update_at'])
  self.assertTrue(state['papers'][0]['summary']);self.assertTrue(state['papers'][0]['favorite']);self.assertTrue(state['papers'][0]['read'])
if __name__=='__main__':unittest.main()
