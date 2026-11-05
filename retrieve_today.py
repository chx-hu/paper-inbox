"""Reuse the read-only Zotero retrieval with a calendar-day morning reference."""
import datetime as dt, sys
from pathlib import Path
base=Path(__file__).resolve().parent
sys.path.insert(0,str(base))
import collector as daily
import json
config=json.loads((base/'sources.json').read_text());daily.setup(config)
import schedule_window
# Midnight local startup still retrieves the same daily window as 06:00.
now=dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
ref=now.replace(hour=6,minute=0,second=0,microsecond=0).astimezone(dt.timezone.utc)
schedule_window.get_scheduled_reference_utc=lambda now=None:ref
# Prefer the supported local API while Zotero is running (sees the current library,
# avoids locked/stale SQLite). Fall back read-only only when unavailable.
original_read=daily.read_corpus
def read_live(db):
 import urllib.request
 items=[];start=0
 try:
  while True:
   url='http://127.0.0.1:23119/api/users/0/items?format=json&limit=100&start='+str(start)
   with urllib.request.urlopen(url,timeout=10) as response:batch=json.load(response)
   if not isinstance(batch,list):raise ValueError('Unexpected Zotero response')
   items.extend(x for x in batch if x.get('data',{}).get('itemType') in ('journalArticle','conferencePaper','preprint') and x.get('data',{}).get('abstractNote','').strip() and not x.get('data',{}).get('deleted'))
   if len(batch)<100:break
   start+=100
  if items:return items
 except Exception:
  pass
 return original_read(db)
daily.read_corpus=read_live
daily.main()
