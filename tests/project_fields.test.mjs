import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PUBLIC_FIELDS, INSTITUTIONAL_FIELDS, getPublicField, getInstitutionalField, formatProjectField, projectFieldCellText } from '../assets/project-fields.js';
import { fieldEvidence, fieldEvidenceHTML, fieldEvidenceText, missingFieldText } from '../assets/field-evidence.js';

test('expansion never inherits a parent fund first-offering amount', () => {
  const fund = {stage:'已上市',initial_raise_cny_100m:20};
  assert.equal(getPublicField({business_type:'扩募'},'sale_amount_cny_100m',{fund,isEvent:true}), null);
  assert.equal(getPublicField({business_type:'首发'},'sale_amount_cny_100m',{fund,isEvent:true}), 20);
});
test('public subjects exclude a standalone issuer and preserve each batch origin', () => {
  assert.equal(getPublicField({origin:'原始权益人'},'issuer'), null);
  assert.equal(PUBLIC_FIELDS.find(f => f.key === 'origin').core, true);
  assert.equal(PUBLIC_FIELDS.some(f => f.key === 'issuer'), false);
  assert.equal(PUBLIC_FIELDS.length, 19);
  const fund = {origin:'首发原始权益人'};
  assert.equal(getPublicField({origin:'扩募原始权益人'},'origin',{fund,isEvent:true}),'扩募原始权益人');
  assert.equal(getPublicField({},'origin',{fund,isEvent:true}),null);
  const event={origin:'扩募原始权益人',source_url:'https://www.sse.com.cn/reits/info/?audit_id=expansion',updated_date:'2026-10-14'};
  const refs=fieldEvidence(event,'origin',{fund,isEvent:true,collectedAt:'2026-10-15T14:13:26+08:00'});
  assert.equal(refs[0].url,event.source_url);
  assert.ok(refs[0].note.includes('2026-10-14'));
  assert.equal(refs[0].published_at,undefined);
  assert.equal(fieldEvidence({origin:event.origin,source_url:'https://etf.sse.com.cn/funddetail/'},'origin',{originSource:event})[0].url,event.source_url);
  assert.equal(fieldEvidence({origin:'企业',source_url:'javascript:alert(1)'},'origin').length,0);
});
test('null issuance evidence stays unknown while false and zero remain explicit', () => {
  const spec = INSTITUTIONAL_FIELDS.find(f => f.key === 'is_issued');
  assert.equal(formatProjectField(getInstitutionalField({status:'4'},'is_issued'),spec),'待核实');
  assert.equal(formatProjectField(false,spec),'否');
  assert.equal(formatProjectField(0,PUBLIC_FIELDS.find(f => f.key === 'external_loan_amount_cny_100m')),'0');
});
test('three document versions stay separate and forecasts retain annualization text', () => {
  const r = {proposed_sale_amount_application_cny_100m:12,proposed_sale_amount_feedback_cny_100m:10,
    project_return_forecast:'IRR为6%；2026年（年化）：7%，2027年：8%'};
  assert.equal(getPublicField(r,'proposed_sale_amount_application_cny_100m'),12);
  assert.equal(getPublicField(r,'proposed_sale_amount_feedback_cny_100m'),10);
  assert.equal(getPublicField(r,'proposed_sale_amount_inquiry_cny_100m'),null);
  assert.equal(getPublicField(r,'project_return_forecast'),r.project_return_forecast);
});
test('disclosure details escape source text and keep unknown reasons separate from zero', () => {
  const record = {research_field_sources:{external_loan_amount_cny_100m:[{title:'<script>bad</script>',url:'https://www.sse.com.cn/file.pdf',published_at:'2026-10-14',page:3}]},field_availability:{financial_advisor:{status:'unverified',reason:'未取得财务顾问证据'}}};
  const view = fieldEvidenceHTML(record,'external_loan_amount_cny_100m');
  assert.ok(view.includes('&lt;script&gt;'));
  assert.ok(view.includes('2026-10-14'));
  assert.ok(view.includes('第3页'));
  assert.equal(missingFieldText(record,'financial_advisor'),'待核实');
  assert.equal(fieldEvidence({research_field_sources:{financial_advisor:[{url:'javascript:alert(1)'}]}},'financial_advisor').length,0);
});

test('local classification overrides evidenced institutional values without borrowing original disclosure evidence', () => {
  const record = {
    id:'SSE_f112c7774ea84dbea54e17bdb33895b5',
    name:'中金-申万-锦欣持有型不动产资产支持专项计划',
    ptype:'产权类', psub:'医疗健康', asset_type:'医疗健康',
    research_field_sources:{asset_type:[{title:'原披露资产说明',url:'https://www.sse.com.cn/medical.pdf',published_at:'2026-10-14',page:3}]}
  };
  const original = structuredClone(record);
  const spec = INSTITUTIONAL_FIELDS.find(field => field.key === 'asset_type');
  const context = {population:'institutional',classification:{ptype:'产权类',psub:'办公',source:'local_manual',note:'根据本次资产说明修订为办公'}};
  assert.equal(getInstitutionalField(record,'asset_type',context),'办公');
  assert.equal(projectFieldCellText(record,spec,context),'办公');
  assert.deepEqual(fieldEvidence(record,'asset_type',context),[]);
  for (const evidence of [fieldEvidenceHTML(record,'asset_type',context),fieldEvidenceText(record,'asset_type',context)]) {
    assert.ok(evidence.includes('本地分类修订'));
    assert.ok(evidence.includes(context.classification.note));
    assert.ok(!evidence.includes('原披露资产说明'));
    assert.ok(!evidence.includes('https://www.sse.com.cn/medical.pdf'));
  }
  const unresolved = {...context,classification:{...context.classification,ptype:'待分类',psub:'待分类'}};
  assert.equal(projectFieldCellText(record,spec,unresolved),'待分类');
  const restored = {population:'institutional',classification:{ptype:'产权类',psub:'医疗健康',source:'verified'}};
  assert.equal(projectFieldCellText(record,spec,restored),'医疗健康');
  assert.ok(fieldEvidenceText(record,'asset_type',restored).includes('原披露资产说明'));
  assert.deepEqual(record,original);
});

test('page and CSV evidence retain every independent calculation, scope and locator', () => {
  const record = {research_field_sources:{proposed_sale_amount_application_cny_100m:[{
    title:'招募说明书（草案）',source_url:'https://www.sse.com.cn/application.pdf',
    published_at:'2026-09-16',page:4,pages:[4,5],checked_at:'2026-10-15T13:14:26+08:00',
    note:'拟发售规模',calculation:'原金额138640万元÷10000',conversion:'万元换算为亿元',
    basis:'申报稿披露金额',amount_nature:'预计或拟发售规模',scope:'首发披露，不含后续扩募'
  }]}};
  const before = structuredClone(record);
  const key = 'proposed_sale_amount_application_cny_100m';
  for (const evidence of [fieldEvidenceHTML(record,key),fieldEvidenceText(record,key)]) {
    for (const expected of ['招募说明书（草案）','2026-09-16','第4、5页','核查：2026-10-15',
      '拟发售规模','原金额138640万元÷10000','万元换算为亿元','申报稿披露金额','预计或拟发售规模',
      '首发披露，不含后续扩募','https://www.sse.com.cn/application.pdf']) assert.ok(evidence.includes(expected),expected);
  }
  assert.ok(fieldEvidenceText(record,key).includes('2026-10-15T13:14:26+08:00'));
  assert.deepEqual(record,before);
  assert.ok(fieldEvidenceText({research_field_sources:{asset_type:[{title:'资产资料',url:'https://www.sse.com.cn/assets.pdf',pages:'12-14'}]}},'asset_type').includes('第12-14页'));
});

test('unavailable field explanations share display reasons and reject unsafe source links in both formats', () => {
  const record = {field_availability:{financial_advisor:{status:'unverified',reason:'内部说明',display_reason:'尚未取得财务顾问证据',source_url:'javascript:alert(1)',checked_at:'2026-10-15T13:14:26+08:00'}}};
  for (const evidence of [fieldEvidenceHTML(record,'financial_advisor'),fieldEvidenceText(record,'financial_advisor')]) {
    assert.ok(evidence.includes('待核实'));
    assert.ok(evidence.includes('尚未取得财务顾问证据'));
    assert.ok(evidence.includes('核查：2026-10-15'));
    assert.ok(!evidence.includes('javascript:'));
    assert.ok(!evidence.includes('内部说明'));
  }
});
