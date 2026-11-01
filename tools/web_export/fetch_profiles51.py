from pathlib import Path
import urllib.request,json,gzip,hashlib
r=Path(__file__).resolve().parents[2]; web=r/'web'
sources=[];values={}
for name,table,year,var in [('populacao','4714','2022','93'),('agro','5938','2021','516')]:
 url=f'https://servicodados.ibge.gov.br/api/v3/agregados/{table}/periodos/{year}/variaveis/{var}?localidades=N6[all]'
 raw=urllib.request.urlopen(url,timeout=50).read();raw=gzip.decompress(raw) if raw[:2]==b'\x1f\x8b' else raw
 data=json.loads(raw);rows={}
 for result in data[0]['resultados']:
  for s in result['series']:
   try:rows[s['localidade']['id']]=float(s['serie'][year])
   except (ValueError,KeyError):pass
 values[name]=rows;sources.append({'field':name,'url':url,'year':year,'sha256':hashlib.sha256(raw).hexdigest(),'count':len(rows)})
 cache=r/'data/raw/web_profiles51';cache.mkdir(parents=True,exist_ok=True)
 (cache/f'{name}_{year}.json').write_bytes(raw)
payload={'sources':sources,'rows':{c:{k:v.get(c) for k,v in values.items()} for c in sorted(set().union(*values.values()))}}
raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'));payload['id']=hashlib.sha256(raw.encode()).hexdigest()[:16]
(web/'src/data/profiles-context.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
print('Context',payload['id'],[(s['field'],s['count']) for s in sources])

dest=web/"public/context";dest.mkdir(exist_ok=True);target=dest/(payload["id"]+".json")
if not target.exists(): target.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
