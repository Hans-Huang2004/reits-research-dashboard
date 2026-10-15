"""Auditable enrichment of every publicly disclosed Shenzhen public REIT filing.

Raw responses/PDFs are immutable, versioned by run. Research values carry exact
PDF-page excerpts. Different filing/expansion batches are kept by official ID.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from collectors import public_szse as source

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / 'data/raw/enrichment/public_szse'
WP_ROOT = ROOT / 'workpapers/enrichment/public_szse'
FIELDS = ('issuer','financial_advisor','proposed_sale_amount_application_cny_100m',
          'proposed_sale_amount_feedback_cny_100m','proposed_sale_amount_inquiry_cny_100m',
          'sale_amount_cny_100m','external_loan_amount_cny_100m','underlying_assets',
          'project_return_forecast','guarantee_support','asset_type')

def now(): return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
def dump(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.name in ('supplement.json','candidate_review.json'):
        index=1
        while path.with_name(path.stem+f'_previous_v{index}'+path.suffix).exists():index+=1
        path.with_name(path.stem+f'_previous_v{index}'+path.suffix).write_bytes(path.read_bytes())
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def compact(text): return re.sub(r'\s+','',text or '')

def refresh():
    run=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S')
    raw=RAW_ROOT/run; wp=WP_ROOT/run
    raw.mkdir(parents=True);wp.mkdir(parents=True)
    packet=source.collect(raw/'project_api')
    reader=source.SourceReader(raw/'announcements')
    sale, sc=source.fetch_announcements(reader,'基金份额发售公告','sales')
    inquiry, ic=source.fetch_announcements(reader,'基金份额询价公告','inquiries')
    packet['announcements']={'sale':sale,'inquiry':inquiry}
    packet['source_status']['additional_announcement_checks']={'sale':sc,'inquiry':ic}
    packet['manifest'] += reader.manifest
    # Announcements bind a code to an exact fund name, including pre-establishment
    # offerings absent from the listed-fund report and contract-effective query.
    existing={f['code']:f for f in packet['funds']}
    for ann in sale:
        if '扩募' in ann['title']:continue
        name=source.fund_name_from_title(ann['title'])
        matches=[e for e in packet['events'] if e['business_type']=='首发' and e['name']==name]
        if len(matches)!=1:continue
        for code in ann.get('secCode',[]):
            if not re.fullmatch(r'18\d{4}',code):continue
            event=matches[0];event['fund_code']=code
            if code not in existing:
                fund={k:event.get(k,'') for k in ('name','exchange','manager','origin','product_type','asset_type','manager_location')}
                fund.update(id='SZSE_FUND_'+code,code=code,short_name=(ann.get('secName') or [''])[0],
                            listing_date='',established_date='',status='发售准备',asset_location='',
                            initial_raise_cny_100m=None,documents=[source.announcement_document(ann)],
                            source_url=source.BASE+'/disclosure/index.html?stock='+code)
                packet['funds'].append(fund);existing[code]=fund
    packet['enrichment_run']=run
    packet['enrichment_paths']={'raw':str(raw),'workpapers':str(wp)}
    dump(wp/'latest_source.json',packet)
    dump(WP_ROOT/'latest_source.json',packet)
    print(json.dumps({'run':run,'events':len(packet['events']),'funds':len(packet['funds']),
                      'sale_announcements':len(sale),'inquiry_announcements':len(inquiry)},ensure_ascii=False),flush=True)
    return packet


def inventory(packet):
    """Only attach secondary offerings within the matching official batch window."""
    docs={};bindings=[]
    announcements=[]
    for kind,rows in packet['announcements'].items():
        for row in rows:
            doc=source.announcement_document(row);doc['kind']=kind;doc['codes']=row.get('secCode',[])
            announcements.append(doc)
    for fund in packet['funds']:
        for row in fund.get('documents',[]):
            doc=dict(row);doc['codes']=[fund['code']]
            doc['kind']='effective' if '合同生效' in doc['title'] else 'listing' if '上市交易公告书' in doc['title'] else 'other'
            announcements.append(doc)
    for event in packet['events']:
        candidates=[]
        for row in event['documents']:
            if '招募说明书' in row['title']:
                doc=dict(row);doc['kind']='prospectus';candidates.append(doc)
        code=event.get('fund_code')
        followons=sorted(e['accepted_date'] for e in packet['events'] if e.get('fund_code')==code and e['business_type']!='首发' and e['accepted_date']>event['accepted_date'])
        upper=followons[0] if event['business_type']!='首发' and followons else '9999-12-31'
        for doc in announcements:
            if code not in doc.get('codes',[]):continue
            followon_doc='扩募' in doc['title']
            if event['business_type']=='首发' and followon_doc:continue
            if event['business_type']!='首发' and (not followon_doc or not (event['accepted_date']<=doc.get('date','')<upper)):continue
            if doc.get('kind') in ('effective','listing','sale','inquiry'):candidates.append(doc)
        # Preserve every official prospectus revision; a stage is inferred only
        # after reading the PDF's own cover/version wording.
        for doc in candidates:
            if not doc.get('url','').lower().endswith('.pdf'):continue
            key=hashlib.sha256(doc['url'].encode()).hexdigest()[:24]
            docs.setdefault(key,dict(doc,key=key))
            bindings.append({'event_id':event['id'],'document_key':key,'kind':doc['kind'],
                             'official_document_type':doc.get('official_document_type'),
                             'title':doc['title'],'published_at':doc.get('date','')})
    dump(Path(packet['enrichment_paths']['workpapers'])/'document_inventory.json',{'documents':docs,'bindings':bindings})
    return docs,bindings


def download_one(doc,raw,wp,max_bytes=20000000):
    import fitz
    key=doc['key'];pdf_path=raw/'pdf'/f'{key}.pdf';text_path=wp/'text'/f'{key}.json'
    pdf_path.parent.mkdir(parents=True,exist_ok=True);text_path.parent.mkdir(parents=True,exist_ok=True)
    started=now();error=None
    for attempt in range(3):
        try:
            if pdf_path.exists():data=pdf_path.read_bytes()
            else:
                req=urllib.request.Request(doc['url'],headers={'User-Agent':'Mozilla/5.0','Referer':source.BASE+'/'})
                with urllib.request.urlopen(req,timeout=60) as response:
                    size=int(response.headers.get('Content-Length') or 0)
                    if size>max_bytes:return dict(doc,status='deferred_range',error='PDF exceeds full-file size limit; await range reader',bytes=size,checked_at=now())
                    data=response.read(max_bytes+1)
                    if len(data)>max_bytes:return dict(doc,status='deferred_range',error='PDF exceeds full-file size limit; await range reader',checked_at=now())
                if not data.startswith(b'%PDF'):raise ValueError('Official URL did not return PDF bytes')
                pdf_path.write_bytes(data)
            digest=hashlib.sha256(data).hexdigest()
            if text_path.exists():text=json.loads(text_path.read_text())
            else:
                pdf=fitz.open(stream=data,filetype='pdf');pages=[pdf[i].get_text('text') for i in range(min(len(pdf),450))]
                text={'sha256':digest,'pages':pages,'page_count':len(pdf),'parsed_page_count':len(pages),'extraction_scope':'first 450 physical PDF pages maximum; long appendices excluded','parser':'PyMuPDF '+fitz.VersionBind}
                dump(text_path,text)
            if text['sha256']!=digest:raise ValueError('PDF/text hash mismatch')
            return dict(doc,status='ok',raw_file=str(pdf_path),text_file=str(text_path),sha256=digest,
                        bytes=len(data),page_count=text['page_count'],extracted_at=started)
        except Exception as exc:
            error=str(exc)
            if attempt<2:time.sleep(attempt+1)
    return dict(doc,status='unavailable',error=error,checked_at=now())


def download(packet,kinds=None):
    docs,bindings=inventory(packet)
    raw=Path(packet['enrichment_paths']['raw']);wp=Path(packet['enrichment_paths']['workpapers'])
    results=[]
    selected={key:doc for key,doc in docs.items() if (not kinds or doc['kind'] in kinds) or (wp/'text'/f'{key}.json').exists()}
    used=sum(p.stat().st_size for p in (raw/'pdf').glob('*.pdf')) if (raw/'pdf').exists() else 0
    if used>3000000000:raise RuntimeError('Raw PDF budget reached; use range reader')
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks={pool.submit(download_one,doc,raw,wp):key for key,doc in selected.items()}
        for n,task in enumerate(as_completed(tasks),1):
            result=task.result();results.append(result)
            if n%10==0 or n==len(tasks):
                print(json.dumps({'downloaded_or_checked':n,'total':len(tasks),'ok':sum(r['status']=='ok' for r in results),
                                  'failed':sum(r['status']!='ok' for r in results)},ensure_ascii=False),flush=True)
                dump(wp/'download_progress.json',{'documents':results,'bindings':bindings})
    manifest={'created_at':now(),'documents':results,'bindings':bindings}
    dump(raw/'pdf_manifest.json',manifest);dump(wp/'download_manifest.json',manifest)
    return manifest


def formal_prospectuses(packet):
    raw=Path(packet['enrichment_paths']['raw']);wp=Path(packet['enrichment_paths']['workpapers'])
    reader=source.SourceReader(raw/'formal_announcement_api')
    rows,check=source.fetch_announcements(reader,'招募说明书','formal_prospectuses')
    dump(raw/'formal_announcement_api'/'manifest.json',{'requests':reader.manifest,'pagination_check':check})
    index=json.loads((wp/'document_inventory.json').read_text())
    dump(wp/'document_inventory_before_formal_v1.json',index)
    added=[]
    for event in packet['events']:
        code=event.get('fund_code')
        if not code or event['business_type']!='首发':continue
        options=[a for a in rows if code in a.get('secCode',[]) and not any(k in a['title'] for k in ('更新','摘要','提示','扩募'))]
        if not options:continue
        ann=min(options,key=lambda a:a.get('publishTime',''))
        doc=source.announcement_document(ann);key=hashlib.sha256(doc['url'].encode()).hexdigest()[:24]
        doc.update(key=key,kind='final_prospectus',codes=[code],scope='最早公开发售版招募说明书；不替代首次申报/反馈版')
        index['documents'][key]=doc
        index['bindings'].append({'event_id':event['id'],'document_key':key,'kind':'final_prospectus','official_document_type':None,'title':doc['title'],'published_at':doc['date']})
        added.append({'event_id':event['id'],'code':code,'document':doc})
    dump(wp/'document_inventory.json',index)
    dump(wp/'formal_prospectus_selection_v1.json',{'selection':'每首发代码最早非更新/摘要/扩募正式招募说明书','pagination_check':check,'selected':added,'manifest':reader.manifest})
    print('formal first-offering prospectuses',len(added),'of',len(packet['funds']),flush=True)
    return index


def range_one(args):
    doc,raw_string,wp_string=args
    raw=Path(raw_string);wp=Path(wp_string);key=doc['key']
    target=wp/'text_ranges'/f'{key}.json';target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():return json.loads(target.read_text())['document']
    import pypdfium2 as pdfium
    from collectors.enrich_public_sse import RangeStream
    stream=None
    original_urlopen=urllib.request.urlopen
    def szse_urlopen(request,*args,**kwargs):
        if isinstance(request,urllib.request.Request) and 'szse.cn' in request.full_url:
            request.add_header('Referer',source.BASE+'/projectdynamic/index.html')
        return original_urlopen(request,*args,**kwargs)
    urllib.request.urlopen=szse_urlopen
    try:
        full=raw/'pdf'/f'{key}.pdf'
        if full.exists():
            pdf=pdfium.PdfDocument(str(full));capture=str(full);digest=hashlib.sha256(full.read_bytes()).hexdigest();retention='complete_pdf'
        else:
            stream=RangeStream(doc['url'],raw/'ranges'/key)
            pdf=pdfium.PdfDocument(stream);capture=str(stream.index_path);retention='partial_http_ranges'
        total=len(pdf);pages=[]
        limit=200 if doc['kind'] in ('prospectus','final_prospectus') else 8
        for i in range(min(total,limit)):
            page=pdf[i];tp=page.get_textpage();pages.append(tp.get_text_range());tp.close();page.close()
        pdf.close()
        if stream and stream.errors:raise RuntimeError('; '.join(stream.errors))
        if stream:digest=hashlib.sha256(stream.index_path.read_bytes()).hexdigest()
        output=dict(doc,status='ok',raw_file=capture,sha256=digest,sha256_type='whole_pdf' if full.exists() else 'range_manifest',
                    retention=retention,page_count=total,parsed_page_count=len(pages),text_file=str(target),extracted_at=now())
        dump(target,{'document':output,'sha256':digest,'pages':pages,'page_count':total,'parsed_page_count':len(pages),'parser':'pypdfium2 HTTP Range/local PDF','retention':retention})
        return output
    except Exception as exc:
        return dict(doc,status='unavailable',error=str(exc)+'; '+('; '.join(stream.errors) if stream else ''),checked_at=now(),retention='partial_http_ranges' if stream else None)
    finally:
        urllib.request.urlopen=original_urlopen


def ranges(packet,kinds=None):
    from concurrent.futures import ProcessPoolExecutor
    raw=Path(packet['enrichment_paths']['raw']);wp=Path(packet['enrichment_paths']['workpapers'])
    inv=json.loads((wp/'document_inventory.json').read_text());old=json.loads((wp/'download_manifest.json').read_text())
    # Every first-acceptance version plus disclosed final revision, one per
    # official source URL. Long legal/valuation appendices are not text-scanned.
    selected=[d for d in inv['documents'].values() if d['kind'] in (kinds or ('prospectus','final_prospectus'))]
    if not kinds:selected += [d for d in old['documents'] if d['status']=='deferred_range']
    results=[]
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(range_one,(d,str(raw),str(wp))):d for d in selected}
        for n,f in enumerate(as_completed(futures),1):
            results.append(f.result())
            if n%5==0 or n==len(futures):
                dump(wp/'range_progress.json',{'finished':n,'total':len(futures),'documents':results})
                print('range documents',n,'/',len(futures),'ok',sum(d['status']=='ok' for d in results),flush=True)
    existing={d['key']:d for d in old['documents']}
    for result in results:
        if result['status']=='ok' or result['key'] not in existing:existing[result['key']]=result
    manifest={'created_at':now(),'documents':list(existing.values()),'bindings':inv['bindings']}
    dump(wp/'download_manifest_ranges_v1.json',manifest)
    dump(wp/'download_manifest.json',manifest)
    dump(raw/'range_capture_manifest_v1.json',{'created_at':now(),'documents':results})
    return manifest


def ocr_effective(packet):
    import fitz
    import subprocess
    wp=Path(packet['enrichment_paths']['workpapers']);raw=Path(packet['enrichment_paths']['raw'])
    path=wp/'download_manifest.json';manifest=json.loads(path.read_text())
    selected=[];images=[]
    for doc in manifest['documents']:
        if doc['status']!='ok' or doc['kind']!='effective':continue
        original=json.loads(Path(doc['text_file']).read_text())
        if sum(len(compact(t)) for t in original['pages'][:3])>100:continue
        full=raw/'pdf'/f"{doc['key']}.pdf"
        if not full.exists():continue
        pdf=fitz.open(str(full));paths=[]
        for index in range(min(3,len(pdf))):
            image=wp/'ocr_images'/f"{doc['key']}_{index+1}.png";image.parent.mkdir(parents=True,exist_ok=True)
            if not image.exists():pdf[index].get_pixmap(matrix=fitz.Matrix(2,2)).save(str(image))
            paths.append(str(image));images.append(str(image))
        selected.append((doc,paths))
    output=wp/'ocr_effective_results_v2.jsonl'
    if not output.exists():
        with output.open('w') as handle:subprocess.run(['/tmp/reits-szse-ocr']+images,stdout=handle,check=True,timeout=600)
    results={row['file']:row for row in [json.loads(line) for line in output.read_text().splitlines()]}
    replacements={}
    for doc,paths in selected:
        pages=[results.get(p,{}).get('text','') for p in paths]
        target=wp/'text_ocr'/f"{doc['key']}.json";target.parent.mkdir(parents=True,exist_ok=True)
        changed=dict(doc,text_file=str(target),text_method='Apple Vision accurate zh-Hans en-US',page_images=paths,ocr_result_file=str(output))
        dump(target,{'document':changed,'sha256':doc['sha256'],'pages':pages,'page_count':doc['page_count'],'parsed_page_count':len(pages),'parser':changed['text_method']})
        replacements[doc['key']]=changed
    manifest['documents']=[replacements.get(d['key'],d) for d in manifest['documents']]
    dump(wp/'download_manifest_ocr_v1.json',manifest);dump(path,manifest)
    print('OCR source documents',len(selected),'pages',len(images),flush=True)
    return manifest


def evidence(doc,page,text,start,end,**extra):
    return {'title':doc['title'],'url':doc['url'],'published_at':doc.get('date',''),
            'page':page,'excerpt':text[max(0,start-60):min(len(text),end+110)],
            'raw_file':doc.get('raw_file'),'sha256':doc.get('sha256'),'sha256_type':doc.get('sha256_type','whole_pdf'),'retention':doc.get('retention','complete_pdf'),'text_method':doc.get('text_method','native_pdf_text'),'page_image':(doc.get('page_images') or [None]*page)[page-1] if page<=len(doc.get('page_images') or []) else None,**extra}


def cny100(value,unit):
    factor={'亿元':Decimal(1),'万元':Decimal('0.0001'),'元':Decimal('0.00000001')}[unit]
    return float(Decimal(value.replace(',',''))*factor)


def forecast_summary(snippet):
    snippet=re.split('基金收益|投保情况|项目权属|回收资金|可供分配金额测算是在|本公告所述',snippet)[0]
    if any(word in snippet for word in ('IRR','内部收益率','资本化率','折现率')):return None
    metric='净现金流分派率' if '净现金流分派率' in snippet else '现金分派率'
    # Sentences explicitly pairing two named years and two rates.
    m=re.search(r'(20\d{2}年)(?:和|及|、)(20\d{2}年)(?:预测)?(?:净现金流|现金)?分派率分别为(\d+(?:\.\d+)?[%％])([（(]年化(?:后)?\d*[）)])?(?:和|及|、)(\d+(?:\.\d+)?[%％])([（(]年化(?:后)?\d*[）)])?',snippet)
    if m:return '预测'+metric+'：'+m.group(1)+('（年化）' if m.group(4) else '')+'：'+m.group(3)+'；'+m.group(2)+('（年化）' if m.group(6) else '')+'：'+m.group(5)
    pairs=[];year_rates={}
    for pair in re.finditer(r'(20\d{2}年[^；。%％]{0,140}?)(\d+(?:\.\d+)?[%％])([（(]年化(?:后)?\d*[）)])?',snippet):
        prefix=pair.group(1)
        if len(set(re.findall(r'20\d{2}',prefix)))!=1:continue
        ym=re.match(r'20\d{2}年(?:度|\d{1,2}月至\d{1,2}月|\d{1,2}月\d{1,2}日[-至]20\d{2}年\d{1,2}月\d{1,2}日)?',prefix)
        annual='（年化）' if '年化' in prefix or pair.group(3) else ''
        year=ym.group(0)[:4];rate=pair.group(2)
        year_rates.setdefault(year,set()).add(rate)
        pairs.append(ym.group(0)+annual+'：'+rate)
    # Multiple rates for the same year are different scenarios or asset pools.
    # A compact automatic summary must not silently merge those scenarios.
    if any(len(rates)>1 for rates in year_rates.values()):return None
    return '预测'+metric+'：'+'；'.join(dict.fromkeys(pairs)) if pairs else None


def extract_document(doc,event,pages):
    candidates=[]
    def add(key,value,n,t,m,**extra):
        if value not in (None,'',[]):candidates.append({'key':key,'value':value,'source':evidence(doc,n,t,m.start(),m.end(),**extra)})
    front=''.join(compact(x) for x in pages[:6])
    stage='application' if doc.get('official_document_type')==1 else 'feedback' if re.search('反馈(?:意见)?稿',front) else 'inquiry' if doc['kind']=='inquiry' or re.search('询价稿',front) else None
    if doc['kind']=='sale' and any(w in front for w in ('询价确定','询价结果','经询价','询价结束')):stage='inquiry'
    company=r'([\u4e00-\u9fffA-Za-z（）()·]{3,70}?(?:股份有限公司|有限责任公司|有限公司))'
    for index,page in enumerate(pages):
        n=index+1;t=compact(page)
        if not t:continue
        if index<120:
            for m in re.finditer(r'财务顾问(?:名称)?[：:]?'+company,t):
                value=re.sub(r'^(?:为|是|系|[（(]如有[）)])','',m.group(1))
                if not any(bad in value for bad in ('本基金','是指','就本','财务顾问','以下简称','基金管理人','原始权益人','基金托管人','运营管理')):
                    other=re.match(r'[、，,]'+company,t[m.end():])
                    if other:value+='、'+other.group(1)
                    add('financial_advisor',value,n,t,m,role='财务顾问')
                    break
            # 独立发行人只接受明确标签；基金管理人及原始权益人不替代。
            for m in re.finditer(r'基金发行人(?:名称)?[：:]'+company,t):
                if not any(bad in t[max(0,m.start()-6):m.start()] for bad in ('债券','其他','证券')):
                    add('issuer',m.group(1),n,t,m,role='公开文本明确列示的发行人')
            underlying_patterns=[
                r'不动产项目名(?:称)?(.{3,500}?)(?:[（(]?预计[）)]?募集规模|拟募集规模|基金管理人)',
                r'基础设施项目名称(.{3,500}?)(?:预计募集规模|基金管理人|基金存续期限|项目类型)',
                r'(?:本基金)?(?:拟投资|初始投资)的?(?:基础设施|不动产)项目(?:包括|为|分别为|系)(.{5,450}?)[。；]',
            ]
            for pattern in underlying_patterns:
                m=re.search(pattern,t)
                if not m:continue
                value=m.group(1).strip('：:，,')
                if event['business_type']!='首发' and len(re.findall(r'首次发行|第[一二三四五]次扩募',value))>1:continue
                if event['business_type']!='首发' and not any(k in t[max(0,m.start()-120):m.end()+100] for k in ('本次扩募','新购入','拟购入')):continue
                value=re.sub(r'[（(]预计[）)]$','',value)
                if len(value)>300 or any(bad in value for bad in ('以下简称','详见本','指本基金','《','目录','标的基础设施项目','股东名称','经营范围','运营表现','业态为','具有保障性质','可能','风险')):continue
                if any(k in value for k in ('项目','物流','大厦','公寓','高速','电站','园','仓','广场','购物','水厂','电厂','环宇','城','酒店','COCOPark','水库')):
                    add('underlying_assets',[value],n,t,m,scope='本次首发/扩募项目正文，未关联其他申报批次')
                    break
            if stage:
                patterns=[r'(?:预计|拟)?募集(?:资金)?(?:总额|规模|金额)[为约：:]?([\d,]+(?:\.\d+)?)(亿元|万元|元)',
                          r'(?:预计募集规模|[（(]预计[）)]募集规模)[（(]亿元[）)]([\d,]+(?:\.\d+)?)']
                for pattern in patterns:
                    m=re.search(pattern,t)
                    if m:
                        raw_value=m.group(1);unit=m.group(2) if len(m.groups())>1 else '亿元'
                        value=cny100(raw_value,unit)
                        if value>0:add('proposed_sale_amount_'+stage+'_cny_100m',value,n,t,m,unit='亿元',source_unit=unit,source_value=raw_value,conversion='原金额按单位换算为亿元',document_stage=stage)
                        break
            # 明确的无借款事实与监管借款比例上限严格区分。
            m=re.search(r'(?:截至本招募说明书出具之日[，,]?项目公司不存在对外借款情况|本基金成立时(?:不进行|不存在|无)对外借款|项目公司不存在(?:银行|对外)借款)',t)
            if m:add('external_loan_amount_cny_100m',0,n,t,m,unit='亿元',basis='正文明确无借款；不以140%/20%等上限推算',as_of=doc.get('date',''))
            m=re.search(r'(?:外部借款|对外借款)(?:金额|余额|本金)?[为：:]?([\d,]+(?:\.\d+)?)(亿元|万元|元)',t)
            if m and not any(k in t[max(0,m.start()-45):m.start()] for k in ('拟','预计','不超过','上限','可','用于','基金成立后')):
                add('external_loan_amount_cny_100m',cny100(m.group(1),m.group(2)),n,t,m,unit='亿元',source_unit=m.group(2),source_value=m.group(1),conversion='原金额按单位换算为亿元',as_of=doc.get('date',''))
            for m in re.finditer(r'(?:预测现金分派率|净现金流分派率|现金分派率|可供分配金额测算)',t):
                snippet=t[max(0,m.start()-90):min(len(t),m.end()+430)]
                if re.search(r'20\d{2}',snippet) and re.search(r'\d(?:\.\d+)?[%％]',snippet):
                    if event['business_type']!='首发' and not any(k in t for k in ('扩募','新购入')):continue
                    summary=forecast_summary(snippet)
                    if summary:add('project_return_forecast',summary,n,t,m,excerpt=snippet,metric='保留原文现金分派率/净现金流分派率及年份、年化口径')
                    break
            for m in re.finditer(r'(?:增信措施|增信安排|担保安排|流动性支持机构|差额补足义务人)[：:]?(.{1,160}?)(?:[。；]|$)',t):
                snippet=m.group(0)
                if any(k in snippet for k in ('有限公司','不适用','未设置','不设置','无增信')) and not any(k in snippet for k in ('落实等事项','重大进展','应当披露','风险')):
                    add('guarantee_support',snippet,n,t,m,scope='明确披露的安排；未由发行人/原始权益人身份推断')
            native=event.get('official_asset_type','')
            if native and native in t and event.get('asset_type') not in ('','待分类',None):
                m=re.search(re.escape(native),t)
                add('asset_type',event['asset_type'],n,t,m,official_asset_type=native,basis='交易所项目类型与本项目PDF正文交叉核验')
        if doc['kind']=='effective':
            m=re.search(r'募集期间净认购金额[（(]单位[：:](?:人民币)?元[）)]((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?)(?![\d,.])',t)
            if m and cny100(m.group(1),'元')>=0.1:
                add('sale_amount_cny_100m',cny100(m.group(1),'元'),n,t,m,unit='亿元',source_unit='元',source_value=m.group(1),conversion='净认购金额除以100000000；不含认购利息',measure='实际募集净认购额')
            m=re.search(r'基金合同生效日(\d{4})年(\d{1,2})月(\d{1,2})日',t)
            if m:add('established_date',datetime(*map(int,m.groups())).date().isoformat(),n,t,m,basis='明确基金合同生效日')
        if doc['kind']=='sale':
            m=re.search(r'(?:本基金)?募集期为(\d{4})年(\d{1,2})月(\d{1,2})日起至(\d{4})年(\d{1,2})月(\d{1,2})日止',t)
            if m:
                add('offering_start_date',datetime(*map(int,m.groups()[:3])).date().isoformat(),n,t,m)
                add('offering_end_date',datetime(*map(int,m.groups()[3:])).date().isoformat(),n,t,m)
    # Retain high-specificity early main-text hits; one source per document/field.
    first={}
    for candidate in candidates:first.setdefault(candidate['key'],candidate)
    return list(first.values())


def extract(packet):
    wp=Path(packet['enrichment_paths']['workpapers']);raw=Path(packet['enrichment_paths']['raw'])
    manifest=json.loads((wp/'download_manifest.json').read_text())
    good={d['key']:d for d in manifest['documents'] if d['status']=='ok'}
    doc_index=json.loads((wp/'document_inventory.json').read_text())
    supplement={'events':{},'funds':{},'coverage':{},'manifest':packet['manifest']+manifest['documents']}
    reviews=[]
    for event in packet['events']:
        relevant=[b for b in doc_index['bindings'] if b['event_id']==event['id']]
        candidates=[];checked=[]
        for binding in relevant:
            doc=good.get(binding['document_key'])
            if not doc:continue
            text=json.loads(Path(doc['text_file']).read_text())
            merged=dict(doc,**{k:v for k,v in binding.items() if k in ('kind','official_document_type','title')})
            candidates+=extract_document(merged,event,text['pages'])
            if any(len(compact(page))>20 for page in text['pages']):
                checked.append({'title':doc['title'],'url':doc['url'],'parsed_pages':len(text['pages']),'total_pages':text['page_count']})
        # Latest document wins within each real stage. Financial adviser and
        # asset text prefer prospectus bodies over sale notices' generic wording.
        candidates.sort(key=lambda c:(c['source'].get('published_at',''),-c['source']['page']),reverse=True)
        fields={};sources={}
        for candidate in candidates:
            key=candidate['key']
            if key not in fields:fields[key]=candidate['value'];sources[key]=[candidate['source']]
        manual_versions=list(wp.glob('manual_reviews_v*.json'))
        manual_path=max(manual_versions,key=lambda p:int(re.search(r'_v(\d+)',p.stem).group(1))) if manual_versions else wp/'manual_reviews_v1.json'
        if manual_path.exists():
            manual=json.loads(manual_path.read_text()).get(event['id'],{})
            fields.update(manual.get('fields',{}));sources.update(manual.get('sources',{}))
        unavailable={}
        bound_keys={b['document_key'] for b in relevant}
        limitations=[{'title':d['title'],'url':d['url'],'status':d['status'],'error':d.get('error'),'parsed_pages':d.get('parsed_page_count'), 'total_pages':d.get('page_count')} for d in manifest['documents'] if d['key'] in bound_keys and (d['status']!='ok' or d.get('parsed_page_count',d.get('page_count',0))<d.get('page_count',0))]
        for key in FIELDS:
            if key in fields:continue
            if not checked:reason='本事件公开PDF未取得可核验正文；'+('；'.join(str(d.get('error') or d['status']) for d in limitations[:2]) or 'PDF为扫描图像或尚无可读正文。')
            elif key=='issuer':reason='已核验正文未独立明确列示基金发行人；不将基金管理人或原始权益人替代。'
            elif key=='proposed_sale_amount_feedback_cny_100m':reason='官方项目附件未标明可核验的反馈稿金额；注册稿不冒充反馈稿。'
            elif key=='sale_amount_cny_100m' and not event.get('fund_code'):reason='本申报尚无已成立基金代码及实际募集结果证据；拟募集金额不替代实际金额。'
            else:reason='未在已核验公开PDF正文中定位到本字段可直接使用的明确值；不以比例上限或其他批次替代。'
            unavailable[key]={'status':'unverified' if checked else 'not_available','original_status':'not_found_in_verified_public_text' if checked else 'document_not_yet_readable',
                              'reason':reason,'source_url':event['source_url'],'checked_at':now()}
        supplement['events'][event['id']]={'fields':fields,'sources':sources,'unavailable':unavailable,'checked_documents':checked,'document_limitations':limitations}
        reviews.append({'event_id':event['id'],'event_name':event['name'],'business_type':event['business_type'],
                        'fields':fields,'sources':sources,'candidate_count':len(candidates)})
    for fund in packet['funds']:
        matches=[e for e in packet['events'] if e['business_type']=='首发' and e.get('fund_code')==fund['code']]
        if len(matches)==1:
            entry=copy.deepcopy(supplement['events'][matches[0]['id']]);entry['source_event_id']=matches[0]['id']
            if fund.get('listing_date'):entry['fields']['stage']='已上市'
            elif entry['fields'].get('established_date'):entry['fields']['stage']='成立待上市'
            elif entry['fields'].get('offering_start_date'):
                today=now()[:10];start=entry['fields']['offering_start_date'];end=entry['fields'].get('offering_end_date','')
                entry['fields']['stage']='待发售' if today<start else '发售中' if today<=end else '募集结束待确认'
            supplement['funds'][fund['code']]=entry
    counts=Counter(key for e in supplement['events'].values() for key in e['fields'])
    supplement['coverage']={'checked_at':now(),'events_total':len(packet['events']),'funds_total':len(packet['funds']),
                             'events_with_readable_pdf':sum(bool(e['checked_documents']) for e in supplement['events'].values()),
                             'event_field_counts':dict(counts),'pdf_ok':len(good),'pdf_failed':len(manifest['documents'])-len(good),
                             'raw_pdf_bytes':sum(p.stat().st_size for p in (raw/'pdf').glob('*.pdf')),
                             'first_issuance_and_followon_separated':True,'unavailable_fields_explicit':True}
    dump(wp/'candidate_review.json',reviews);dump(wp/'supplement.json',supplement);dump(WP_ROOT/'supplement.json',supplement)
    print(json.dumps(supplement['coverage'],ensure_ascii=False,indent=2),flush=True)
    return supplement


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['refresh','download','formal-prospectuses','ranges','ranges-formal','ocr-effective','extract']);parser.add_argument('--kinds',default='effective,sale,inquiry');args=parser.parse_args()
    if args.command=='refresh':refresh()
    elif args.command=='formal-prospectuses':formal_prospectuses(json.loads((WP_ROOT/'latest_source.json').read_text()))
    elif args.command=='ocr-effective':ocr_effective(json.loads((WP_ROOT/'latest_source.json').read_text()))
    elif args.command=='ranges':ranges(json.loads((WP_ROOT/'latest_source.json').read_text()))
    elif args.command=='ranges-formal':ranges(json.loads((WP_ROOT/'latest_source.json').read_text()),('final_prospectus',))
    elif args.command=='download':download(json.loads((WP_ROOT/'latest_source.json').read_text()),set(args.kinds.split(',')))
    else:extract(json.loads((WP_ROOT/'latest_source.json').read_text()))
