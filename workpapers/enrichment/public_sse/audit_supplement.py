"""Offline source/field reconciliation for the frozen SSE supplement."""
import hashlib,json,re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from collectors.enrich_public_sse import ROOT,WORK,save,now
x=json.loads((WORK/'supplement.json').read_text());src=json.loads((WORK/'latest_source.json').read_text());events={e['id']:e for e in src['events']}
docs=json.loads((WORK/'inventory.json').read_text())+json.loads((WORK/'announcement_inventory.json').read_text());known={d['url']:d for d in docs}
errors=[];checks=[];fields=0;texts={};units={'亿元':Decimal(1),'万元':Decimal('0.0001'),'元':Decimal('0.00000001')}
for eid,e in x['events'].items():
 if eid not in events:errors.append([eid,'unknown event'])
 if set(e['fields'])&set(e['unavailable']):errors.append([eid,'value and unavailable overlap'])
 for f,v in e['fields'].items():
  fields+=1
  if not e['sources'].get(f):errors.append([eid,f,'no evidence']);continue
  for s in e['sources'][f]:
   for k in ['url','title','published_at','page','excerpt','text_workpaper']:
    if not s.get(k):errors.append([eid,f,'missing '+k])
   if s['url'] not in known:errors.append([eid,f,'unknown document URL'])
   elif known[s['url']]['event_id']!=eid:errors.append([eid,f,'document event mismatch'])
   if s.get('text_workpaper'):
    p=ROOT/s['text_workpaper'];t=texts.setdefault(str(p),json.loads(p.read_text()));start=s['page'];end=s.get('page_end',start)
    body=re.sub(r'\s+','',''.join(t['pages'][start-1:end]));excerpt=re.sub(r'\s+','',s['excerpt'])
    if excerpt not in body:errors.append([eid,f,'excerpt not in retained pages',start])
   if 'amount_' in f and isinstance(v,(int,float)):
    expected=Decimal(s['raw_amount'].replace(',',''))*units[s['raw_unit']];diff=abs(Decimal(str(v))-expected)
    checks.append({'event_id':eid,'field':f,'value':v,'raw_amount':s['raw_amount'],'raw_unit':s['raw_unit'],'difference_cny_100m':str(diff)})
    if diff>Decimal('0.000000005'):errors.append([eid,f,'unit conversion differs',str(diff)])
    if v<0 or v>500:errors.append([eid,f,'implausible money value',v])
actual_checks=[]
for eid,e in x['events'].items():
 if 'sale_amount_cny_100m' not in e['fields']:continue
 event=events[eid];bs=[b for b in src['issuance_batches'] if b['fund_code']==event.get('fund_code') and b['business_type']==event['business_type']]
 if len(bs)!=1:errors.append([eid,'actual amount batch is ambiguous']);continue
 b=bs[0];estimate=Decimal(str(b['price_cny']))*Decimal(str(b['copies_100m']));diff=abs(Decimal(str(e['fields']['sale_amount_cny_100m']))-estimate)*Decimal(100000000)
 actual_checks.append({'event_id':eid,'fund_code':event.get('fund_code'),'actual_cny_100m':e['fields']['sale_amount_cny_100m'],'price_times_offered_units_cny_100m':str(estimate),'difference_cny':str(diff),'check_only':'比较价格×发售份额，仅作独立数量级校验，不据此生成实际募集金额。'})
 if diff>50:errors.append([eid,'actual amount differs materially from official price/unit cross-check',str(diff)])
result={'checked_at':now(),'supplement_sha256':hashlib.sha256((WORK/'supplement.json').read_bytes()).hexdigest(),'event_keys':len(x['events']),'filled_fields':fields,'money_cells':len(checks),'coverage':dict(Counter(f for e in x['events'].values() for f in e['fields'])),'errors':errors,'unit_recalculations':checks,'actual_amount_independent_cross_checks':actual_checks,'status':'passed' if not errors else 'failed'}
save(WORK/'consistency_audit.json',result)
print(json.dumps({k:result[k] for k in ['status','event_keys','filled_fields','money_cells','errors']},ensure_ascii=False))
