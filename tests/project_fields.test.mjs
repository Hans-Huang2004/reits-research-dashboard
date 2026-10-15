import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PUBLIC_FIELDS, INSTITUTIONAL_FIELDS, getPublicField, getInstitutionalField, formatProjectField } from '../assets/project-fields.js';
import { fieldEvidence, fieldEvidenceHTML, missingFieldText } from '../assets/field-evidence.js';

test('expansion never inherits a parent fund first-offering amount', () => {
  const fund = {stage:'已上市',initial_raise_cny_100m:20};
  assert.equal(getPublicField({business_type:'扩募'},'sale_amount_cny_100m',{fund,isEvent:true}), null);
  assert.equal(getPublicField({business_type:'首发'},'sale_amount_cny_100m',{fund,isEvent:true}), 20);
});
test('issuer does not silently become originator', () => {
  assert.equal(getPublicField({origin:'原始权益人'},'issuer'), null);
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
  const record = {research_field_sources:{external_loan_amount_cny_100m:[{title:'<script>bad</script>',url:'https://www.sse.com.cn/file.pdf',published_at:'2026-10-14',page:3}]},field_availability:{issuer:{status:'unverified',reason:'未取得独立发行人证据'}}};
  const view = fieldEvidenceHTML(record,'external_loan_amount_cny_100m');
  assert.ok(view.includes('&lt;script&gt;'));
  assert.ok(view.includes('2026-10-14'));
  assert.ok(view.includes('第3页'));
  assert.equal(missingFieldText(record,'issuer'),'待核实');
  assert.equal(fieldEvidence({research_field_sources:{issuer:[{url:'javascript:alert(1)'}]}},'issuer').length,0);
});
