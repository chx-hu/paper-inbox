"""Conservative fallback for explicit first-page institutions in official PDFs."""
import json,re,shutil,subprocess
from pathlib import Path
from urllib.request import Request,urlopen
from arxiv_metadata import arxiv_id_from_url
BASE=Path(__file__).resolve().parents[1]/'cache'/'arxiv-pdf-metadata'
ORG=re.compile(r'\b(?:University|Universität|Institute|Instituto|Laborator(?:y|ies)|College|School of|Department of|Corporation|Inc\.|Ltd\.|GmbH)',re.I)
def parse_affiliations(text,authors):
 lines=text.splitlines();started=False;result=[]
 tokens=[re.findall(r'\w+',a.lower()) for a in authors]
 for line in lines:
  line=re.sub(r'\s+',' ',line).strip()
  if re.match(r'^(?:\d+\s+)?Abstract\b',line,re.I):break
  words=set(re.findall(r'\w+',line.lower()))
  is_author=any(len(t)>=2 and set(t)<=words for t in tokens)
  if is_author:started=True;continue
  if started and '@' not in line and len(line)<500 and ORG.search(line):
   line=re.sub(r'^[\d,*†‡\s]+','',line)
   if line not in result:result.append(line)
 return result

def enrich_pdf(p):
 out=dict(p)
 if out.get('affiliations'):return out
 aid=arxiv_id_from_url(out.get('url',''))
 exe=shutil.which('pdftotext') or '/opt/homebrew/bin/pdftotext'
 if not aid or not Path(exe).exists():return out
 BASE.mkdir(parents=True,exist_ok=True)
 stem=aid.replace('/','_');pdf=BASE/(stem+'.pdf');txt=BASE/(stem+'.txt');source='https://arxiv.org/pdf/'+aid
 try:
  if not txt.exists():
   if not pdf.exists():
    with urlopen(Request(source,headers={'User-Agent':'PaperInbox/0.1'}),timeout=15) as r:raw=r.read(8*1024*1024+1)
    if not raw.startswith(b'%PDF') or len(raw)>8*1024*1024:raise ValueError('invalid_or_large_pdf')
    pdf.write_bytes(raw)
   subprocess.run([exe,'-f','1','-l','1','-layout',str(pdf),str(txt)],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  found=parse_affiliations(txt.read_text(errors='replace'),out.get('authors',[]))
  if found:
   out['affiliations']=found
   out['metadata_sources']=list(dict.fromkeys(out.get('metadata_sources',[])+[source]))
   out.pop('metadata_note',None)
 except Exception as exc:out['metadata_note']='arXiv 单位补充未完成（'+type(exc).__name__+'）'
 return out
