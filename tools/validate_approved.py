#!/usr/bin/env python3
"""Reject structurally invalid public approvals; human source review is still required."""
import json,re,sys
from pathlib import Path
from urllib.parse import urlparse
p=Path(sys.argv[1] if len(sys.argv)>1 else 'agent/data/approved.json')
if not p.exists():
    print('No published-listing data file found; initial shop remains published.');sys.exit(0)
try: data=json.loads(p.read_text(encoding='utf-8'))
except Exception as e:sys.exit('Invalid JSON: '+str(e))
if data.get('format')!='HOV-APPROVED-1' or not isinstance(data.get('listings'),list):sys.exit('Expected HOV-APPROVED-1 and listings array')
if len(data['listings'])>1200:sys.exit('Too many approved listings')
seen=set()
for i,r in enumerate(data['listings'],1):
 if not isinstance(r,dict):sys.exit(f'Listing {i} not an object')
 ident=r.get('id');title=r.get('title');url=r.get('url');cats=r.get('cats');status=r.get('status')
 if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{4,120}',ident):sys.exit(f'Listing {i}: invalid ID')
 if ident in seen:sys.exit(f'Listing {i}: duplicate ID')
 seen.add(ident)
 if not isinstance(title,str) or not 8<=len(title)<=200:sys.exit(f'Listing {i}: missing title')
 u=urlparse(url) if isinstance(url,str) else None
 if not u or u.scheme!='https' or not u.hostname or u.username or u.password:sys.exit(f'Listing {i}: official source must use a normal HTTPS link')
 if status not in ('program','invite'):sys.exit(f'Listing {i}: must have approved status')
 if not isinstance(cats,list) or not cats or any(not isinstance(c,str) for c in cats):sys.exit(f'Listing {i}: missing categories')
 if not isinstance(r.get('country'),str) or not r['country'].strip():sys.exit(f'Listing {i}: country required')
 # Source-level proof, real reward/conditions and review date avoid accidental publication.
 if not isinstance(r.get('provider'),str) or not r['provider'].strip():sys.exit(f'Listing {i}: provider required')
 if not isinstance(r.get('what'),str) or len(r['what'].strip())<20:sys.exit(f'Listing {i}: exact benefit/terms required')
 if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',str(r.get('reviewed',''))):sys.exit(f'Listing {i}: verification date required')
 if r.get('verified_source') is not True:sys.exit(f'Listing {i}: verified_source must be true')
print(f'Validated {len(data["listings"])} public listings; original source and eligibility still require editorial checks.')
