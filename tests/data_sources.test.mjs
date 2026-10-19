import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sourceBeijingDate, formatSourceTimestamp, sourceStatusSummary, sourceStatusReloadDue } from '../assets/data-sources.js';

const now = '2026-10-19T10:00:00+08:00';
const joint = () => ({ status: 'complete', attempt_ok: true, date: '2026-10-19', completed_at: '2026-10-19T07:30:00+08:00', last_successful_at: '2026-10-19T07:30:00+08:00', validation: { public: { ok: true, issued_funds: 97, filings: 160 }, institutional: { count: 132 } } });

test('successful batches expose only validated population counts and success time', () => {
  const value = joint();
  const publicStatus = sourceStatusSummary(value, { population: 'public', now });
  assert.equal(publicStatus.code, 'complete');
  assert.equal(publicStatus.statusLabel, '已更新');
  assert.equal(publicStatus.dataDate, '2026-10-19');
  assert.equal(publicStatus.lastSuccessfulText, '2026-10-19 07:30');
  assert.deepEqual(publicStatus.counts, { issuedFunds: 97, filings: 160 });
  assert.deepEqual(sourceStatusSummary(value, { population: 'institutional', now }).counts, { records: 132 });
  assert.equal(value.validation.public.issued_funds, 97);
});
test('failed attempts preserve the actual previous success and do not promote attempt date or old counts', () => {
  const failed = { ...joint(), status: 'failed', attempt_ok: false, date: '2026-10-19', completed_at: '2026-10-19T09:00:00+08:00', last_attempt_at: '2026-10-19T08:55:00+08:00', last_successful_at: '2026-10-18T07:30:00+08:00' };
  const result = sourceStatusSummary(failed, { now });
  assert.equal(result.code, 'failed');
  assert.equal(result.statusLabel, '本轮未完成');
  assert.equal(result.dataDate, '2026-10-18');
  assert.equal(result.lastSuccessfulText, '2026-10-18 07:30');
  assert.deepEqual(result.counts, {});
  delete failed.last_successful_at;
  assert.equal(sourceStatusSummary(failed, { now }).lastSuccessfulText, '未取得');
});
test('a failed attempt flag overrides a complete status', () => {
  assert.equal(sourceStatusSummary({ ...joint(), attempt_ok: false }, { now }).code, 'failed');
});
test('population validation failure overrides a complete batch status and its success description', () => {
  const value = joint();
  value.validation.public.ok = false;
  const result = sourceStatusSummary(value, { population: 'public', now });
  assert.equal(result.code, 'failed');
  assert.equal(result.statusLabel, '本轮未完成');
  assert.equal(result.description, '保留上次完整快照。');
  assert.deepEqual(result.counts, {});
  assert.equal(sourceStatusSummary(value, { population: 'institutional', now }).code, 'complete');
  const ndrc = { status: 'complete', attempt_ok: true, date: '2026-10-19', last_successful_at: '2026-10-19T07:45:00+08:00', validation: { ok: false, items: 137 } };
  assert.equal(sourceStatusSummary(ndrc, { population: 'ndrc', now }).code, 'failed');
});
test('a prior complete batch is marked pending update and retains its valid counts', () => {
  const previous = { ...joint(), date: '2026-10-18', completed_at: '2026-10-18T07:30:00+08:00', last_successful_at: '2026-10-18T07:30:00+08:00' };
  const result = sourceStatusSummary(previous, { now });
  assert.equal(result.code, 'stale');
  assert.equal(result.statusLabel, '待更新');
  assert.deepEqual(result.counts, { issuedFunds: 97, filings: 160 });
});
test('missing or incomplete metadata remains unknown rather than claiming success', () => {
  for (const value of [null, undefined, {}, { status: 'complete' }, { status: 'running', last_attempt_at: now }, []]) {
    const result = sourceStatusSummary(value, { now });
    assert.equal(result.code, 'pending');
    assert.equal(result.statusLabel, '待读取');
    assert.deepEqual(result.counts, {});
  }
});
test('a running or pending batch preserves the known prior success in its label and description', () => {
  for (const status of ['running', 'pending']) {
    const result = sourceStatusSummary({ status, date: '2026-10-19', last_attempt_at: now, last_successful_at: '2026-10-18T07:30:00+08:00' }, { now });
    assert.equal(result.code, 'pending');
    assert.equal(result.statusLabel, '本轮待完成');
    assert.equal(result.dataDate, '2026-10-18');
    assert.equal(result.lastSuccessfulText, '2026-10-18 07:30');
    assert.equal(result.description, '本轮更新尚未完成，保留上次成功快照。');
    assert.deepEqual(result.counts, {});
  }
});
test('status metadata reloads after sixty seconds, including a backward clock adjustment', () => {
  assert.equal(sourceStatusReloadDue(0, 100000), true);
  assert.equal(sourceStatusReloadDue(undefined, 100000), true);
  assert.equal(sourceStatusReloadDue(100000, 159999), false);
  assert.equal(sourceStatusReloadDue(100000, 160000), true);
  assert.equal(sourceStatusReloadDue(100000, 200000), true);
  assert.equal(sourceStatusReloadDue(100000, 99999), true);
});
test('count zero remains a disclosed count, with missing and invalid count fields left unknown', () => {
  const value = joint();
  value.validation.public = { ok: true, issued_funds: 0, filings: '160' };
  assert.deepEqual(sourceStatusSummary(value, { now }).counts, { issuedFunds: 0, filings: null });
  value.validation.public.ok = false;
  assert.deepEqual(sourceStatusSummary(value, { now }).counts, {});
});
test('NDRC counts use recommendation validation rather than the joint schema', () => {
  const ndrc = { status: 'complete', date: '2026-10-19', last_successful_at: '2026-10-19T07:45:00+08:00', validation: { ok: true, items: 137 } };
  assert.deepEqual(sourceStatusSummary(ndrc, { population: 'ndrc', now }).counts, { records: 137 });
});
test('Beijing midnight defines freshness independently of execution timezone', () => {
  const value = { ...joint(), date: '2026-10-18', last_successful_at: '2026-10-18T07:30:00+08:00' };
  assert.equal(sourceStatusSummary(value, { now: '2026-10-18T15:59:59Z' }).code, 'complete');
  assert.equal(sourceStatusSummary(value, { now: '2026-10-18T16:00:00Z' }).code, 'stale');
  assert.equal(sourceBeijingDate('2026-10-18T16:00:00Z'), '2026-10-19');
  assert.equal(formatSourceTimestamp('2026-10-18T16:00:00Z'), '2026-10-19 00:00');
});
test('dates require valid calendar values and timestamps require an explicit timezone', () => {
  assert.equal(sourceBeijingDate('2026-10-19'), '2026-10-19');
  for (const value of ['2026-02-30', '2026-13-01', '2026-02-30T07:30:00Z', 'not-a-date', '2026-10-19T07:30:00', null]) assert.equal(sourceBeijingDate(value), '');
  assert.equal(formatSourceTimestamp('2026-10-19'), '未取得');
});
test('future completion times cannot be reported as a successful current batch', () => {
  assert.equal(sourceStatusSummary({ ...joint(), last_successful_at: '2026-10-19T11:00:00+08:00' }, { now }).code, 'pending');
  assert.equal(sourceStatusSummary({ ...joint(), date: '2026-10-20' }, { now }).code, 'pending');
});
test('failed status reads keep prior success visible while suspending current success and counts', () => {
  const result = sourceStatusSummary(joint(), { now, readError: true });
  assert.equal(result.code, 'unavailable');
  assert.equal(result.lastSuccessfulText, '2026-10-19 07:30');
  assert.deepEqual(result.counts, {});
});
