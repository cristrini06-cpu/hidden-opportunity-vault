#!/usr/bin/env python3
"""Write an explicit real-world scan status. Only run by a connected scheduler."""
import datetime as dt, json, sys
from pathlib import Path
base=Path(__file__).resolve().parent/'data'
base.mkdir(parents=True, exist_ok=True)
p=base/'agent_status.json'
try: current=json.loads(p.read_text(encoding='utf8'))
except Exception: current={}
now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def iso(v):return str(v or '')
status={'format':'HOV-STATUS-1','state':current.get('state','not_configured'),
 'updated_at':now,'started_at':iso(current.get('started_at')),
 'finished_at':iso(current.get('finished_at')),'last_run_at':iso(current.get('last_run_at')),
 'sources_scanned':int(current.get('sources_scanned',0)),
 'sources_configured':int(current.get('sources_configured',0)),
 'errors':int(current.get('errors',0)),'message':str(current.get('message',''))}
if len(sys.argv)<2 or sys.argv[1] not in ('start','finish'):
 raise SystemExit('Usage: python agent/status.py start|finish [success|failure]')
if sys.argv[1]=='start':
 status.update(state='running',started_at=now,updated_at=now,message='Scheduled scan started; waiting for results.')
else:
 try: report=json.loads((base/'discoveries.json').read_text(encoding='utf8'))
 except Exception: report={}
 outcome=sys.argv[2] if len(sys.argv)>2 else 'failure'
 valid=outcome=='success' and report.get('format')=='HOV-AGENT-1' and bool(report.get('generated_at'))
 if valid:
  status.update(state='complete',last_run_at=iso(report['generated_at']),finished_at=now,
   sources_scanned=int(report.get('sources_scanned') or 0),sources_configured=int(report.get('sources_configured') or 0),
   errors=len(report.get('failures') or []),message='Scan completed; candidates require verification.')
 else:status.update(state='failed',finished_at=now,message='Scan failed. Review scheduled workflow logs.')
p.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print('Agent status:',status['state'])
