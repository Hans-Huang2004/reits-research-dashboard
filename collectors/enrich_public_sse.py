"""Versioned official-document enrichment for SSE public REIT filings.

Run with the bundled Python runtime (pypdfium2/pypdf). Raw PDFs stay immutable;
page text, candidates and reviewed fields are separate workpapers. Never infer an
actual offering amount from a draft, or assign expansion assets to first issuance.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import hashlib
import io
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from collectors.public_sse import RawClient, fetch_pages, now, clean

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'workpapers/enrichment/public_sse'
FIELDS = ('issuer','financial_advisor','proposed_sale_amount_application_cny_100m',
          'proposed_sale_amount_feedback_cny_100m','proposed_sale_amount_inquiry_cny_100m',
          'sale_amount_cny_100m','external_loan_amount_cny_100m','underlying_assets',
          'project_return_forecast','guarantee_support','asset_type')


def save(path, value):
    path = Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)


def compact(value):
    return re.sub(r'\s+','',value or '')


def run_paths():
    run=json.loads((WORK/'run.json').read_text())
    return ROOT / Path(run['raw_dir']).parent, WORK


def inventory(source):
    result=[]
    for e in source['events']:
        # All disclosed prospectus versions, rather than three misleading fixed
        # labels. Version 3 is a registration/sealed draft, not an inquiry notice.
        ds=[d for d in e['documents'] if d.get('official_file_type')=='93' or '招募说明书' in d.get('title','')]
        for d in ds:
            result.append(dict(d,event_id=e['id'],business_type=e['business_type'],
                fund_code=e.get('fund_code',''),document_stage={'1':'application','2':'feedback','3':'sealed'}.get(d.get('official_version'),'unknown'),kind='prospectus'))
    latest={}
    for doc in result:
        if doc['event_id'] not in latest or (doc.get('date',''),doc.get('official_version','')) > (latest[doc['event_id']].get('date',''),latest[doc['event_id']].get('official_version','')):
            latest[doc['event_id']]=doc
    return sorted(result,key=lambda d:(d is not latest[d['event_id']],d['event_id'],d.get('date','')))


def document_key(doc):
    return hashlib.sha256(doc['url'].encode()).hexdigest()[:24]


def download(docs,raw_root,workers=6):
    client=RawClient(raw_root/'pdfs')
    def get(doc):
        key=document_key(doc)
        try:
            body=client.get(doc['url'],label='pdf_'+key,raw=True)
            if not body.startswith(b'%PDF'):
                raise ValueError('Official URL did not return a PDF')
            m=client.cache[(doc['url'],'{}')]
            return dict(doc,key=key,raw_file=str((client.raw_dir/m['file']).relative_to(ROOT)),sha256=m['sha256'],bytes=len(body),download_status='ok',retrieved_at=m['retrieved_at'])
        except Exception as exc:
            return dict(doc,key=key,download_status='unavailable',error=str(exc),checked_at=now())
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i,f in enumerate(as_completed([pool.submit(get,d) for d in docs]),1):
            results.append(f.result())
            if i%10==0:
                save(WORK/'download_progress.json',{'finished':i,'total':len(docs),'ok':sum(d['download_status']=='ok' for d in results),'at':now()})
                print('downloaded',i,'/',len(docs),flush=True)
    return sorted(results,key=lambda d:(d['event_id'],d.get('date',''),d['key']))


def extract_one(doc):
    if doc.get('download_status')!='ok':return doc
    target=WORK/'texts'/(doc['key']+'.json')
    if target.exists():
        old=json.loads(target.read_text())
        if old.get('sha256')==doc['sha256']:
            return dict(doc,text_file=str(target.relative_to(ROOT)),pages=len(old['pages']),text_status=old['text_status'])
    pages=[];error=''
    try:
        import pypdfium2 as pdfium
        pdf=pdfium.PdfDocument(str(ROOT/doc['raw_file']))
        for page in pdf:
            textpage=page.get_textpage()
            pages.append(textpage.get_text_range())
            textpage.close();page.close()
        pdf.close()
        if sum(map(len,pages)) < 50*min(len(pages),10):
            from pypdf import PdfReader
            pages=[p.extract_text() or '' for p in PdfReader(ROOT/doc['raw_file']).pages]
    except Exception as exc:error=str(exc)
    status='ok' if pages and sum(map(len,pages))>100 else 'unreadable'
    save(target,{'key':doc['key'],'sha256':doc['sha256'],'source_url':doc['url'],'text_status':status,'error':error,'pages':pages,'extracted_at':now()})
    return dict(doc,text_file=str(target.relative_to(ROOT)),pages=len(pages),text_status=status,error=error)


def extract_all(docs,workers=6):
    # PDFium is not thread-safe. Separate processes isolate native documents.
    from concurrent.futures import ProcessPoolExecutor
    result=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i,doc in enumerate(pool.map(extract_one,docs),1):
            result.append(doc)
            if i%10==0:
                save(WORK/'extraction_progress.json',{'finished':i,'total':len(docs),'ok':sum(d.get('text_status')=='ok' for d in result),'at':now()})
                print('extracted',i,'/',len(docs),flush=True)
    return result


class RangeStream(io.BufferedIOBase):
    """Seekable official PDF retaining only the byte ranges actually read.

    The captured ranges plus the request/index are immutable Raw inputs. This is
    deliberately labelled partial source retention, never a complete PDF copy.
    """
    BLOCK=512*1024
    def __init__(self,url,directory):
        super().__init__();self.url=url;self.directory=Path(directory);self.errors=[]
        self.directory.mkdir(parents=True,exist_ok=True);self.position=0;self.memory={}
        self.index_path=self.directory/'index.json'
        if self.index_path.exists():self.index=json.loads(self.index_path.read_text())
        else:
            error=None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url,method='HEAD',headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.sse.com.cn/'}),timeout=30) as r:
                        self.index={'url':url,'bytes':int(r.headers['Content-Length']),'etag':r.headers.get('ETag'),'last_modified':r.headers.get('Last-Modified'),'head_retrieved_at':now(),'retention':'HTTP Range responses for accessed PDF objects; not the complete source PDF','ranges':{}}
                    save(self.index_path,self.index);break
                except Exception as exc:
                    error=exc;time.sleep(attempt+1)
            else:raise RuntimeError('PDF metadata unavailable: '+str(error))
        self.length=self.index['bytes']
        # Small notices are cheaper and stronger to retain as one complete
        # response. This also avoids benign CDN HEAD/GET mtime ETag differences.
        full=self.directory/'verified_complete.bin'
        if self.length<=6*1024*1024 and not full.exists():
            with urllib.request.urlopen(urllib.request.Request(self.url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.sse.com.cn/'}),timeout=40) as r:
                body=r.read();headers=dict(r.headers)
            if len(body)!=self.length:raise RuntimeError('Complete PDF length differs from HEAD')
            for entry in self.index['ranges'].values():
                if body[entry['start']:entry['end']+1]!=(self.directory/entry['file']).read_bytes():raise RuntimeError('Complete PDF differs from previously captured source ranges')
            full.write_bytes(body)
            save(self.directory/'full_response_verification.json',{'url':self.url,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'headers':headers,'retrieved_at':now(),'matched_all_prior_raw_ranges':True,'retention':'complete official PDF response'})
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        self.position=offset if whence==0 else self.position+offset if whence==1 else self.length+offset
        if self.position<0:raise ValueError('Negative PDF byte position')
        return self.position
    def _block(self,number):
        if number in self.memory:return self.memory[number]
        start=number*self.BLOCK;end=min(self.length-1,start+self.BLOCK-1)
        path=self.directory/(str(start)+'-'+str(end)+'.bin')
        entry=self.index['ranges'].get(str(number))
        full=self.directory/'verified_complete.bin'
        if full.exists():
            with full.open('rb') as stream:stream.seek(start);b=stream.read(end-start+1)
            self.memory[number]=b;return b
        if entry and path.exists():
            b=path.read_bytes()
            if hashlib.sha256(b).hexdigest()!=entry['sha256']:raise RuntimeError('Range hash mismatch')
        else:
            error=None
            for attempt in range(3):
                try:
                    req=urllib.request.Request(self.url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.sse.com.cn/','Range':f'bytes={start}-{end}'})
                    with urllib.request.urlopen(req,timeout=40) as r:
                        if r.status!=206:raise RuntimeError('Server did not honor byte range')
                        etag=r.headers.get('ETag')
                        if self.index.get('etag') and etag and etag!=self.index['etag']:raise RuntimeError('PDF version changed during range retrieval')
                        content_range=r.headers.get('Content-Range','')
                        if content_range!=f'bytes {start}-{end}/{self.length}':raise RuntimeError('Unexpected PDF content range')
                        b=r.read()
                    if len(b)!=end-start+1:raise RuntimeError('Truncated PDF byte range')
                    path.write_bytes(b)
                    self.index['ranges'][str(number)]={'start':start,'end':end,'file':path.name,'sha256':hashlib.sha256(b).hexdigest(),'retrieved_at':now(),'content_range':content_range}
                    save(self.index_path,self.index);break
                except Exception as exc:
                    error=exc;time.sleep(attempt+1)
            else:
                self.errors.append(str(error))
                # ctypes callbacks suppress Python exceptions. Return no bytes
                # immediately and reject the whole extraction after native close.
                return b''
        self.memory[number]=b
        return b
    def read(self,size=-1):
        if self.errors:return b''
        if size<0:size=self.length-self.position
        end=min(self.length,self.position+size);parts=[]
        while self.position<end:
            number=self.position//self.BLOCK;b=self._block(number)
            offset=self.position-number*self.BLOCK;n=min(end-self.position,len(b)-offset)
            if n<=0:break
            parts.append(b[offset:offset+n]);self.position+=n
        return b''.join(parts)
    def readinto(self,b):
        result=self.read(len(b));b[:len(result)]=result;return len(result)


def range_extract_one(job):
    doc,raw_root,max_pages=job;key=document_key(doc)
    target=WORK/'texts'/(key+'.json')
    if target.exists():
        old=json.loads(target.read_text())
        if old.get('text_status')=='ok' and len(old['pages'])>=min(old.get('total_pages',len(old['pages'])),max_pages):
            return dict(doc,key=key,text_file=str(target.relative_to(ROOT)),pages=len(old['pages']),total_pages=old.get('total_pages',len(old['pages'])),text_status='ok',source_retention=old.get('source_retention','complete PDF'))
    try:
        import pypdfium2 as pdfium
        stream=RangeStream(doc['url'],Path(raw_root)/'ranges'/key)
        pdf=pdfium.PdfDocument(stream)
        count=len(pdf);pages=[]
        for n in range(min(count,max_pages)):
            page=pdf[n];tp=page.get_textpage();pages.append(tp.get_text_range());tp.close();page.close()
        pdf.close()
        if stream.errors:raise RuntimeError('Source byte retrieval incomplete: '+str(set(stream.errors)))
        status='ok' if sum(map(len,pages))>100 else 'unreadable'
        info={'key':key,'source_url':doc['url'],'text_status':status,'pages':pages,'total_pages':count,'extracted_pages':len(pages),'extracted_at':now(),'source_retention':'HTTP Range source bytes for accessed pages and PDF metadata; unexamined appendices are not retained','range_index':str(stream.index_path.relative_to(ROOT)),'etag':stream.index.get('etag')}
        save(target,info)
        return dict(doc,key=key,text_file=str(target.relative_to(ROOT)),pages=len(pages),total_pages=count,text_status=status,source_retention=info['source_retention'],range_index=info['range_index'])
    except Exception as exc:
        if 'pages' in locals() and pages and sum(map(len,pages))>100 and not stream.errors:
            info={'key':key,'source_url':doc['url'],'text_status':'ok','pages':pages,'total_pages':count,'extracted_pages':len(pages),'extracted_at':now(),'source_retention':'HTTP Range source bytes for successfully read pages; later pages unavailable','range_index':str(stream.index_path.relative_to(ROOT)),'unavailable_from_page':len(pages)+1,'read_error':str(exc),'etag':stream.index.get('etag')}
            save(target,info)
            return dict(doc,key=key,text_file=str(target.relative_to(ROOT)),pages=len(pages),total_pages=count,text_status='ok',read_error=str(exc),range_index=info['range_index'])
        return dict(doc,key=key,text_status='unavailable',error=str(exc),checked_at=now())


def range_extract_all(docs,raw_root,workers=3,max_pages=350):
    from concurrent.futures import ProcessPoolExecutor
    result=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i,doc in enumerate(pool.map(range_extract_one,[(d,str(raw_root),max_pages) for d in docs]),1):
            result.append(doc)
            save(WORK/('announcement_documents_progress.json' if doc.get('kind')=='announcement' else 'prospectus_documents_progress.json'),result)
            if i%5==0:print('range-extracted',i,'/',len(docs),'ok',sum(d.get('text_status')=='ok' for d in result),flush=True)
    return result


PATTERNS={
 'issuer':[r'发行人[：:]',r'(?:由|发起募集人[：:])[^。；]{0,70}(?:依法募集|发起募集|公开募集)'],
 'financial_advisor':[r'(?:基金管理人)?财务顾问[：:]',r'财务顾问[\s\S]{0,30}(?:证券|资本|银行)[^。；]{0,25}公司'],
 'proposed_amount':[r'(?:拟|预计|计划)?(?:募集|发售)(?:资金)?(?:总额|规模|金额)[^。；]{0,90}(?:亿元|万元|人民币元)',r'基金发行规模[^。；]{0,90}'],
 'external_loan_amount_cny_100m':[r'(?:外部借款|外部贷款|新增借款|本基金借款|拟借款|拟贷款)[^。；]{0,180}',r'(?:本次交易|本次扩募)[^。；]{0,100}(?:借款|贷款)[^。；]{0,100}'],
 'underlying_assets':[r'(?:本基金|基础设施基金|不动产基金)(?:拟)?(?:初始|首次)?(?:投资|持有|购入|收购)[^。；]{0,260}(?:项目|资产)',r'本次(?:拟)?(?:新购入|扩募)[^。；]{0,200}(?:项目|资产)',r'(?:标的|底层|初始投资的|拟购入的)(?:基础设施|不动产)?项目[^。；]{0,220}'],
 'project_return_forecast':[r'(?:20\d{2}[^。；]{0,100})?(?:现金流分派率|年化分派率|年化收益率|预测分派率|项目收益率|全投资[^。；]{0,10}内部收益率|IRR)[^。；]{0,220}'],
 'guarantee_support':[r'(?:差额补足|差额支付|流动性支持|收益补足)[^。；]{0,200}',r'(?:原始权益人|发起人|运营管理机构)[^。；]{0,70}(?:担保|保底|补足)[^。；]{0,130}',r'(?:不设置|不设|无)(?:担保|差额补足)[^。；]{0,100}'],
 'sale_amount_cny_100m':[r'(?:募集资金(?:总额|金额)|募集净认购金额|募集有效认购总户数)[^。；]{0,150}',r'(?:发售|募集)(?:总额|规模|金额)[^。；]{0,90}(?:亿元|万元|元)'],
}


def candidates(docs):
    result={}
    for doc in docs:
        if doc.get('text_status')!='ok':continue
        pages=json.loads((ROOT/doc['text_file']).read_text())['pages']
        fields={}
        for field,patterns in PATTERNS.items():
            hits=[]
            for page_no,page in enumerate(pages,1):
                p=compact(page)
                for pattern in patterns:
                    for m in re.finditer(pattern,p):
                        start=max(0,m.start()-100);end=min(len(p),m.end()+150)
                        excerpt=p[start:end]
                        # ToC lines and generic cover disclaimers are candidates,
                        # not filled fields; human review selects factual passages.
                        hits.append({'page':page_no,'match':m.group(0),'excerpt':excerpt,'offset':m.start()})
            # Keep enough context for all source versions and larger asset pools.
            unique={(h['page'],h['offset']):h for h in hits}
            fields[field]=list(unique.values())
        result[doc['key']]={'document':doc,'candidates':fields}
    return result


def query_announcements(source,raw_root):
    client=RawClient(raw_root/'announcements')
    jobs=[]
    for batch in source.get('issuance_batches',[]):
        start=batch.get('start_date')
        if not start:continue
        dt=datetime.fromisoformat(start)
        begin=(dt-timedelta(days=45)).strftime('%Y-%m-%d')
        end=batch.get('listing_date') or min((dt+timedelta(days=90)).strftime('%Y-%m-%d'),now()[:10])
        if end<begin:end=now()[:10]
        jobs.append((batch,begin,end))
    def one(job):
        batch,begin,end=job
        try:
            rows,check=fetch_pages(client,'REITS_BULLETIN',params={'fundCode':batch['fund_code'],'startDate':begin,'endDate':end},identity=lambda r:(r.get('url'),r.get('title')))
            chosen=[]
            for row in rows:
                title=clean(row.get('title'))
                if not re.search('询价公告|发售公告|合同生效公告|募集结果|募集情况|上市交易公告|上市提示性|扩募份额上市',title):continue
                if not row.get('url'):continue
                chosen.append({'title':title,'url':row['url'].replace('http://','https://',1) if row['url'].startswith('http') else 'https://www.sse.com.cn'+row['url'],'date':clean(row.get('sseDate'))[:10],'fund_code':batch['fund_code'],'kind':'announcement','business_type':batch['business_type'],'batch_start':batch['start_date'],'document_stage':'inquiry' if '询价公告' in title else 'offering' if '发售公告' in title else 'establishment' if '生效公告' in title else 'listing'})
            return {'batch':batch,'startDate':begin,'endDate':end,'check':check,'documents':chosen}
        except Exception as exc:
            return {'batch':batch,'startDate':begin,'endDate':end,'error':str(exc),'documents':[]}
    with ThreadPoolExecutor(max_workers=6) as pool:result=list(pool.map(one,jobs))
    return result,client.manifest


def announcement_inventory(source,queries):
    unique={}
    for query in queries:
        batch=query['batch']
        events=[e for e in source['events'] if e.get('fund_code')==batch['fund_code'] and e['business_type']==batch['business_type']]
        if len(events)!=1:continue
        groups={}
        for doc in query['documents']:
            d=dict(doc);d['url']=d['url'].replace('http://','https://',1)
            if '延期' in d['title'] or '提示性' in d['title'] and d['document_stage'] in ('inquiry','offering'):continue
            if d['document_stage'] in ('inquiry','offering') and d['date']>batch['start_date']:continue
            if batch['business_type']=='首发' and '扩募' in d['title']:continue
            if batch['business_type']=='扩募' and '扩募' not in d['title']:continue
            groups.setdefault(d['document_stage'],[]).append(d)
        for group in groups.values():
            d=max(group,key=lambda x:x['date']);d['event_id']=events[0]['id']
            unique[d['url']]=d
    return list(unique.values())


def evidence(doc,page,excerpt,rule,**extra):
    return {'title':doc['title'],'url':doc['url'],'published_at':doc.get('date',''),
            'page':page,'excerpt':excerpt,'document_stage':doc.get('document_stage',''),
            'rule':rule,'reviewed_at':now(),**extra}


def normalized_lines(page):
    return [re.sub('[ \t\u3000]+',' ',line).strip() for line in page.replace('\r','').split('\n') if line.strip()]


def concise_forecast(text):
    """Preserve explicit years and rate bases; remove generic risk preambles."""
    text=compact(text)
    text=re.sub(r'^.*?(?=(?:20\d{2}|净现金流分派率|现金流分派率|预测分派率|预计年化))','',text)
    text=re.split('(?:基金收益预计|基金收益分配|基金管理人|原始权益人|投保情况|股权转让|回收资金用途|现金流法律顾问|第[一二三四五六七八九十]+节|发行价格)',text)[0]
    text=re.sub(r'^.*?(?=净现金流分派率|现金流分派率|预测分派率|预测现金分派率|预计年化分派率)','',text)
    # A PDF superscript footnote following a rate is not part of that rate.
    text=re.sub(r'(?<=%)[1-9](?=[截至本，；和及])','',text)
    rates=list(re.finditer('%',text))
    result=text[:rates[-1].end()] if rates else ''
    result=re.sub(r'(?<=%)(?=20\d{2})','；',result)
    return result if result and len(result)<=450 else ''


def structured_candidates(doc):
    textfile=WORK/'texts'/(document_key(doc)+'.json')
    if not textfile.exists():return {'document':doc,'fields':{},'status':'not_available'}
    data=json.loads(textfile.read_text());pages=data.get('pages',[])
    if data.get('text_status')!='ok':return {'document':doc,'fields':{},'status':data.get('text_status')}
    fields={}
    def add(field,value,page,excerpt,rule,**extra):
        if field=='underlying_assets':
            value=re.split(r'基金存续期限|专项计划期限|[（(]?预计[）)]?募集规模|大类资产类型|不动产类型',value)[0]
            # A definition cut in the middle of a numbered asset pool would
            # silently omit other projects. Leave it pending a pool-level review.
            if rule=='defined_named_initial_assets' and (re.search(r'（1）|\(1\)|第十四部分|历次扩募|目标基础设施项目与',value) or len(value)>320):return
        if field=='project_return_forecast' and '净现金流分派率' in excerpt and value.startswith('现金流分派率'):
            value='净'+value
        if data.get('method')=='local_vision_ocr':
            extra.update(source_method='local_vision_ocr',ocr_page_image=str((WORK/'ocr'/document_key(doc)/(str(page)+'.png')).relative_to(ROOT)),ocr_rows=str((WORK/'ocr'/document_key(doc)/(str(page)+'.json')).relative_to(ROOT)))
        else:extra['source_method']='native_pdf_text'
        extra['text_workpaper']=str(textfile.relative_to(ROOT))
        if value not in (None,'',[]):fields.setdefault(field,[]).append({'value':value,'source':evidence(doc,page,excerpt,rule,**extra)})
    for no,page in enumerate(pages,1):
        p=compact(page);lines=normalized_lines(page)
        if doc.get('document_stage') in ('establishment','listing') and no<=18:
            for pattern in [r'(?:有效净认购金额|净认购金额|净认购总额)(?:（不含利息）|\(不含利息\))?(?:为|是|：|:)(?:人民币)?([0-9][0-9,.]*)(?:元人民币|元)',r'募集期间净认购金额(?:（单位[：:](?:人民币)?元）)?([0-9][0-9,.]*)',r'(?:募集资金总额|募集金额|实际募集金额)(?:为|是|：|:)(?:人民币)?([0-9][0-9,.]*)(亿元|万元|元)']:
                for m in re.finditer(pattern,p):
                    excerpt=p[max(0,m.start()-80):m.end()+120]
                    if any(k in excerpt for k in ['拟募集','计划募集','预计募集']):continue
                    unit=m.group(2) if m.lastindex and m.lastindex>=2 else '元'
                    value=float(m.group(1).replace(',',''))*{'亿元':1,'万元':1e-4,'元':1e-8}[unit]
                    add('sale_amount_cny_100m',round(value,10),no,excerpt,'explicit_actual_net_subscription_amount',raw_amount=m.group(1),raw_unit=unit,currency='CNY',normalized_unit='亿元',amount_nature='公告披露的实际净认购/募集金额；是否含利息依原文')
        if no<=65:
            for index,line in enumerate(lines):
                c=compact(line)
                # Table rows and explicit definitions identify the adviser. Never
                # reuse the fund/ABS manager merely because it is a securities firm.
                if re.match(r'^(?:[（(]?[一二三四五六七八九十\d]+[)）、.．]?)?财务顾问',c):
                    snippet=' '.join(lines[index:index+6])
                    window=compact(snippet).split('财务顾问',1)[1]
                    window=re.split(r'原始权益人|运营管理(?:机构|统筹机构)|招募说明书签署日期',window)[0]
                    if re.match(r'^(?:[（(]如有[）)])?[：:]?(?:无|不涉及)(?:$|[，。；])',window):
                        add('financial_advisor','无',no,snippet,'explicit_no_financial_adviser')
                    m=re.search(r'([\u4e00-\u9fffA-Za-z（）()·-]{3,65}?(?:股份有限公司|有限责任公司|有限公司))',window)
                    if m:
                        v=m.group(1)
                        v=re.split(r'指|为|：|本基金首次发售时|本次扩募时|本基金的财务顾问',v)[-1].strip('，、：:')
                        v=re.sub(r'^(?:名称|财务顾问)+','',v)
                        v=re.sub(r'^(?:[（(]如有[）)]|即|系)+','',v)
                        if len(v)>=6 and ('证券' in v or '资本' in v or '银行' in v or v=='中国国际金融股份有限公司') and not any(k in v for k in ['基金管理人','首次发售时','财务顾问服务']):
                            add('financial_advisor',v,no,snippet,'explicit_adviser_row_or_definition')
                # Preserve line boundaries so a superscript footnote is not
                # concatenated to the decimal amount (14.61 followed by note 1).
                for label in ['预计募集规模','拟募集规模','拟发售金额','基金募集规模','募集资金规模']:
                    if not c.startswith(label):continue
                    snippet=' '.join(lines[index:index+3])
                    pattern=re.escape(label)+r'\s*[（(](亿元|万元|元)[）)]\s*([0-9][0-9,.]*)'
                    m=re.search(pattern,snippet)
                    unit=None;v=None
                    if m:unit=m.group(1);v=m.group(2)
                    else:
                        m=re.search(re.escape(label)+r'\s*(?:为|约|：|:)?\s*([0-9][0-9,.]*)\s*(亿元|万元|元)',snippet)
                        if m:v=m.group(1);unit=m.group(2)
                    if v and unit and not any(k in snippet[:100] for k in ['不低于','不超过','上限','区间','测算，则','测算,则']):
                        value=float(v.replace(',',''))*{'亿元':1,'万元':1e-4,'元':1e-8}[unit]
                        add('proposed_amount',round(value,8),no,snippet,'explicit_proposed_monetary_scale',raw_amount=v,raw_unit=unit,currency='CNY',normalized_unit='亿元',amount_nature='预计或拟发售规模')
                if re.match(r'^(?:基础设施|不动产)?项目名称(?:\s|[:：]|$)',line):
                    snippet=' '.join(lines[index:index+6]);value=re.sub(r'^(?:基础设施|不动产)?项目名称\s*[:：]?\s*','',snippet)
                    value=re.split(r'(?:不动产项目业态|基础设施(?:类型|项目类型)|项目业态|项目所在地|资产范围|[（(]?预计[）)]?募集规模|[（(]?拟[）)]?上市|大类资产类型|不动产类型|基金存续期限|专项计划期限|基金管理人|项目公司名称|项目类别)',value)[0].strip()
                    if value and len(value)<=500 and not any(k in value[:40] for k in ['第','附表','以下简称','……','其他情况']):add('underlying_assets',compact(value),no,snippet,'named_underlying_project_table')
                if re.match(r'^(?:不动产项目业态|基础设施(?:项目)?(?:类型|类别)|项目业态|资产类型)',c):
                    snippet=' '.join(lines[index:index+3]);add('asset_description',compact(snippet)[:180],no,snippet,'explicit_asset_use_table')
            # Summary prose for older disclosure templates and expansion assets.
            for m in re.finditer(r'(?:本基金拟初始投资的(?:基础设施|不动产)?项目为|本基金初始投资的(?:基础设施|不动产)?项目为|本次拟购入的(?:基础设施|不动产)?项目(?:包括|为)|本基金拟初始投资的基础设施资产为)([^。；]{8,330})',p):
                if not any(k in m.group(1)[:50] for k in ['详见','如下','按照','符合']):add('underlying_assets',m.group(1),no,m.group(0),'explicit_initial_or_new_assets_sentence')
            if no<=40:
                for m in re.finditer(r'(?:基础设施项目|不动产项目|基础设施资产|标的基础设施项目)[：:]指([^。；]{10,330})',p):
                    v=m.group(1)
                    if any(k in v for k in ['位于','园区','物流','公路','大厦','电站','住房','购物中心','污水','焚烧']) and not any(k in v[:35] for k in ['符合','法律法规','本基金可以','中国证监会']):add('underlying_assets',v,no,m.group(0),'defined_named_initial_assets')
            # Year plus forecast metric must coexist in the retained passage.
            for m in re.finditer(r'净现金流分派率|现金流分派率|现金分派率|现金流分配率|年化收益率|分派率/IRR|全周期IRR',p):
                excerpt=p[max(0,m.start()-160):m.start()+650]
                if re.search(r'20\d{2}',excerpt) and '%' in excerpt and not any(k in excerpt for k in ['如初始募集规模超过','敏感性分析','可能低于','交易价格上涨']):
                    value=concise_forecast(excerpt)
                    if value:add('project_return_forecast',value,no,excerpt,'explicit_year_and_forecast_rate')
        # Financed amount: an explicit absence is zero; an upper limit remains
        # unavailable, and intra-structure shareholder loans are excluded.
        for m in re.finditer(r'(?:本基金|本次交易|本次扩募)[^。；]{0,60}(?:不涉及|不进行|未安排|不安排)外部(?:借款|贷款)',p):
            add('external_loan_amount_cny_100m',0.0,no,p[max(0,m.start()-60):m.end()+100],'explicit_no_external_borrowing',raw_amount='0',raw_unit='元',normalized_unit='亿元',currency='CNY',amount_nature='本次交易安排')
        for m in re.finditer(r'外部(?:借款|贷款)(?:金额|规模|本金)?(?:为|约为|：|:)([0-9][0-9,.]*)(亿元|万元|元)',p):
            excerpt=p[max(0,m.start()-80):m.end()+100]
            if any(k in excerpt[:m.start()-max(0,m.start()-80)+8] for k in ['上限','不超过','不高于','最高','限额','不得']):continue
            if not any(k in excerpt for k in ['本基金','本次交易','本次扩募','拟借入','拟安排']):continue
            value=float(m.group(1).replace(',',''))*{'亿元':1,'万元':1e-4,'元':1e-8}[m.group(2)]
            add('external_loan_amount_cny_100m',round(value,8),no,excerpt,'explicit_transaction_external_borrowing',raw_amount=m.group(1),raw_unit=m.group(2),normalized_unit='亿元',currency='CNY',amount_nature='文件披露的交易融资安排，非期末债务余额')
        for m in re.finditer(r'差额补足|差额支付|流动性支持|收益补足',p):
            begin=max(p.rfind('。',0,m.start())+1,m.start()-180)
            end=p.find('。',m.end())
            if end<0 or end>m.end()+220:continue
            excerpt=p[begin:end+1]
            if any(k in excerpt for k in ['不得','不保证','第十八条','第十九条','不超过20%','根据法律法规']):continue
            if re.search(r'出具|签署|应当|应向|承担|承诺|提供|有义务|履行',excerpt) and re.search(r'公司|银行|原始权益人|运营管理机构|担保人|补足义务人',excerpt):
                add('guarantee_support',excerpt,no,excerpt,'specific_support_obligation_passage')
    return {'document':doc,'fields':fields,'status':'ok','extracted_pages':len(pages),'total_pages':data.get('total_pages',len(pages))}


def collect_structured_candidates():
    docs=json.loads((WORK/'inventory.json').read_text())
    if (WORK/'announcement_inventory.json').exists():docs+=json.loads((WORK/'announcement_inventory.json').read_text())
    result=[structured_candidates(d) for d in docs]
    save(WORK/'structured_candidates.json',result)
    return result


def select_candidates(source,rows):
    selected={}
    for event in source['events']:
        docs=[r for r in rows if r['document'].get('event_id')==event['id'] and r['status']=='ok']
        prospectuses=sorted([r for r in docs if r['document']['kind']=='prospectus'],key=lambda r:(r['document'].get('date',''),r['document'].get('official_version','')),reverse=True)
        latest=prospectuses[0] if prospectuses else None
        fields={};sources={}
        def choose(field,candidate):
            if candidate:
                fields[field]=candidate['value'];sources[field]=[candidate['source']]
        if latest:
            for field in ['financial_advisor','project_return_forecast','guarantee_support','external_loan_amount_cny_100m']:
                options=latest['fields'].get(field,[])
                if event['business_type']=='扩募' and field=='project_return_forecast':
                    options=[c for c in options if any(k in c['source']['excerpt'] for k in ['扩募后基金','新购入资产','新增资产','拟购入项目'])]
                if field=='project_return_forecast':options=[c for c in options if '20' in c['value'] and '%' in c['value']]
                if options:choose(field,min(options,key=lambda c:(c['source']['page'],len(c['value']) if isinstance(c['value'],str) else 0)))
            assets=latest['fields'].get('underlying_assets',[])
            if event['business_type']=='扩募':
                assets=[c for c in assets if any(k in c['source']['excerpt'] for k in ['本次拟购入','本次新购入','本次扩募拟','本次新增'])]
            if assets:
                # Prefer the explicit whole-pool sentence/definition to a table
                # row describing only one property in a larger portfolio.
                candidate=min(assets,key=lambda c:(c['source']['rule']=='named_underlying_project_table',c['source']['page']))
                choose('underlying_assets',candidate)
            descriptions=latest['fields'].get('asset_description',[])
            if descriptions:
                desc=descriptions[0]
                from collectors.institutional import classify_by_name
                cls=classify_by_name(desc['value'])
                if cls['psub']!='待分类':
                    choose('asset_type',{'value':cls['psub'],'source':dict(desc['source'],classification_basis='官方披露资产用途转研究资产分类')})
            for stage,target in [('application','proposed_sale_amount_application_cny_100m'),('feedback','proposed_sale_amount_feedback_cny_100m')]:
                stage_docs=[r for r in prospectuses if r['document'].get('document_stage')==stage]
                if stage_docs:
                    doc=min(stage_docs,key=lambda r:r['document'].get('date','')) if stage=='application' else max(stage_docs,key=lambda r:r['document'].get('date',''))
                    options=doc['fields'].get('proposed_amount',[])
                    if options:choose(target,min(options,key=lambda c:c['source']['page']))
        announcements=[r for r in docs if r['document'].get('kind')=='announcement']
        actual=[c for r in announcements for c in r['fields'].get('sale_amount_cny_100m',[])]
        if actual:choose('sale_amount_cny_100m',min(actual,key=lambda c:(c['source']['document_stage']!='establishment',c['source']['page'])))
        inquiry=[c for r in announcements if r['document'].get('document_stage')=='inquiry' for c in r['fields'].get('proposed_amount',[])]
        if inquiry:choose('proposed_sale_amount_inquiry_cny_100m',min(inquiry,key=lambda c:c['source']['page']))
        source_url=latest['document']['url'] if latest else event['source_url']
        unavailable={field:{'status':'unverified','reason':'已检索公开正文，尚未取得足以确认该字段的明确披露；不以主体近似、贷款上限或其他阶段金额替代。','source_url':source_url,'checked_at':now()} for field in FIELDS if field not in fields}
        unavailable['issuer']={'status':'unverified','reason':'未找到单独标识发行人且可直接确认主体的披露，未将原始权益人或基金管理人自动代填发行人。','source_url':source_url,'checked_at':now()}
        selected[event['id']]={'fields':fields,'sources':sources,'unavailable':unavailable,'latest_document':latest['document'] if latest else None,'document_status':{'total_listed':len([d for d in rows if d['document'].get('event_id')==event['id']]),'readable':len(docs)}}
    return selected


def build_supplement(include_narratives=False):
    """Publish only the field families whose candidate passages were reviewed.

    Narrative candidates are deliberately a separate audit pass: reading an
    unrelated historic pool or a sensitivity table is not sufficient evidence.
    """
    from collections import Counter
    source=json.loads((WORK/'latest_source.json').read_text())
    rows=collect_structured_candidates()
    selected=select_candidates(source,rows)
    save(WORK/'selected_candidates.json',selected)
    accepted={'financial_advisor','proposed_sale_amount_application_cny_100m',
              'proposed_sale_amount_feedback_cny_100m','proposed_sale_amount_inquiry_cny_100m',
              'sale_amount_cny_100m','external_loan_amount_cny_100m'}
    if include_narratives:accepted.update({'asset_type','underlying_assets','project_return_forecast','guarantee_support'})
    for event in selected.values():
        for field in list(event['fields']):
            if field not in accepted:
                event['unavailable'][field]={'status':'unverified','reason':'最新公开正文已读取；抽取候选尚在逐项审核，确认后补录。','source_url':event['sources'][field][0]['url'],'checked_at':now()}
                del event['fields'][field];del event['sources'][field]
            else:
                for item in event['sources'][field]:
                    item['review_status']='passage_reviewed'
        event.pop('latest_document',None)
    review_path=WORK/'manual_review.json'
    if review_path.exists():
        review=json.loads(review_path.read_text())
        if review.get('source_run_stamp')!=json.loads((WORK/'run.json').read_text())['stamp']:raise ValueError('Narrative review belongs to a different source run')
        for eid,row in review.get('events',{}).items():
            for field,value in row['fields'].items():
                selected[eid]['fields'][field]=value
                selected[eid]['sources'][field]=row['sources'][field]
                selected[eid]['unavailable'].pop(field,None)
    counts=Counter(k for row in selected.values() for k in row['fields'])
    latest={}
    for doc in json.loads((WORK/'inventory.json').read_text()):
        if doc['event_id'] not in latest or (doc.get('date',''),doc.get('official_version',''))>(latest[doc['event_id']].get('date',''),latest[doc['event_id']].get('official_version','')):latest[doc['event_id']]=doc
    readable=0
    for doc in latest.values():
        path=WORK/'texts'/(document_key(doc)+'.json')
        if path.exists() and json.loads(path.read_text()).get('text_status')=='ok':readable+=1
    raw_root,_=run_paths()
    result={'events':selected,'funds':{},'coverage':{'exchange':'上交所','events':len(selected),'latest_prospectuses':len(latest),'latest_prospectuses_readable':readable,'fields_verified':dict(counts),'field_unit':'金额统一为人民币亿元；原单位与换算见逐字段证据','generated_at':now(),'narrative_review_complete':include_narratives},
            'manifest':{'source':str((WORK/'latest_source.json').relative_to(ROOT)),'raw_directory':str(raw_root.relative_to(ROOT)),'source_manifest':str((raw_root/'source/manifest.json').relative_to(ROOT)),'announcement_manifest':str((WORK/'announcement_manifest.json').relative_to(ROOT)),'candidate_workpaper':str((WORK/'structured_candidates.json').relative_to(ROOT)),'narrative_review_workpaper':str(review_path.relative_to(ROOT)),'range_retention':'大文件按实际读取的HTTP Range响应保留，index.json记录版本与分段哈希；小文件保留完整官方响应。未读取附录不代表已完成全文核查。','generated_at':now()}}
    save(WORK/'supplement.json',result)
    return result


def ocr_existing_documents():
    """Read scanned source pages locally; retain image and positional OCR rows."""
    import pypdfium2 as pdfium
    raw_root,_=run_paths();docs=json.loads((WORK/'announcement_inventory.json').read_text())
    docs=[d for d in docs if d['document_stage'] in ('establishment','listing')]
    docs+= [d for d in json.loads((WORK/'inventory.json').read_text()) if d['event_id']=='SSE_35723']
    done=[]
    for doc in docs:
        key=document_key(doc);target=WORK/'texts'/(key+'.json')
        if not target.exists():continue
        old=json.loads(target.read_text())
        if old.get('text_status')=='ok':continue
        directory=WORK/'ocr'/key;directory.mkdir(parents=True,exist_ok=True)
        try:
            stream=RangeStream(doc['url'],raw_root/'ranges'/key)
            pdf=pdfium.PdfDocument(stream);total=len(pdf);pages=[]
            count=min(total,55 if doc.get('kind')=='prospectus' else 3)
            for n in range(count):
                image_path=directory/(str(n+1)+'.png');rows_path=directory/(str(n+1)+'.json')
                if not rows_path.exists():
                    page=pdf[n];bitmap=page.render(scale=2.5);image=bitmap.to_pil();image.save(image_path);page.close()
                    proc=subprocess.run([str(WORK/'ocr_vision'),str(image_path)],capture_output=True,text=True,timeout=30)
                    if proc.returncode:raise RuntimeError('Local OCR failed: '+proc.stderr[:150])
                    save(rows_path,json.loads(proc.stdout))
                rows=json.loads(rows_path.read_text());pages.append('\n'.join(r['text'] for r in rows))
            pdf.close()
            if stream.errors:raise RuntimeError(str(stream.errors))
            save(directory/'metadata.json',{'document':doc,'pages':count,'total_pages':total,'method':'Apple Vision local OCR, accurate zh-Hans/en-US, 2.5x source-page rendering','checked_at':now(),'range_index':str(stream.index_path.relative_to(ROOT))})
            save(target,dict(old,pages=pages,text_status='ok' if sum(map(len,pages))>100 else 'unreadable',total_pages=total,extracted_pages=count,method='local_vision_ocr',ocr_directory=str(directory.relative_to(ROOT)),extracted_at=now()))
            done.append({'event_id':doc['event_id'],'key':key,'pages':count,'status':'ok'})
        except Exception as exc:done.append({'event_id':doc['event_id'],'key':key,'status':'unavailable','reason':str(exc)})
        save(WORK/'ocr_progress.json',done)
        print('ocr',len(done),doc['event_id'],done[-1]['status'],flush=True)
    return done


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['inventory','download','extract','range-extract','candidates','announcements','announcement-extract','supplement','ocr'])
    parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args()
    source=json.loads((WORK/'latest_source.json').read_text())
    raw_root,_=run_paths()
    if args.phase=='inventory':
        docs=inventory(source);save(WORK/'inventory.json',docs)
        print(json.dumps({'events':len(source['events']),'prospectus_versions':len(docs),'events_with_prospectus':len(set(d['event_id'] for d in docs))},ensure_ascii=False))
    elif args.phase=='download':save(WORK/'downloads.json',download(json.loads((WORK/'inventory.json').read_text()),raw_root,args.workers))
    elif args.phase=='extract':save(WORK/'documents.json',extract_all(json.loads((WORK/'downloads.json').read_text()),args.workers))
    elif args.phase=='range-extract':save(WORK/'documents.json',range_extract_all(json.loads((WORK/'inventory.json').read_text()),raw_root,args.workers))
    elif args.phase=='candidates':save(WORK/'candidates.json',candidates(json.loads((WORK/'documents.json').read_text())))
    elif args.phase=='announcements':
        results,manifest=query_announcements(source,raw_root);save(WORK/'announcements.json',results)
        save(WORK/'announcement_manifest.json',manifest)
        print('announcements',sum(len(r['documents']) for r in results),'query failures',sum('error' in r for r in results))
    elif args.phase=='announcement-extract':
        docs=announcement_inventory(source,json.loads((WORK/'announcements.json').read_text()))
        save(WORK/'announcement_inventory.json',docs)
        save(WORK/'announcement_documents.json',range_extract_all(docs,raw_root,args.workers,max_pages=60))
    elif args.phase=='supplement':
        print(json.dumps(build_supplement()['coverage'],ensure_ascii=False))
    elif args.phase=='ocr':save(WORK/'ocr_documents.json',ocr_existing_documents())


if __name__=='__main__':main()
