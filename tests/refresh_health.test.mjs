import { test } from 'node:test';
import assert from 'node:assert/strict';
import { refreshWarning } from '../assets/refresh-health.js';

test('a missed morning refresh is visible at 08:00 Beijing, across the UTC date boundary', () => {
  const old = { date: '2026-10-15' };
  assert.equal(refreshWarning(old, new Date('2026-10-15T23:59:00Z')), '');
  assert.match(refreshWarning(old, new Date('2026-10-16T00:00:00Z')), /今日刷新尚未完成/);
  assert.equal(refreshWarning({ date: '2026-10-16' }, new Date('2026-10-16T01:00:00Z')), '');
});

test('a stale joint batch is not hidden by a newer individual snapshot label', () => {
  assert.match(refreshWarning({ date: '2026-10-16', refresh_batch: { date: '2026-10-15' } },
    new Date('2026-10-16T01:00:00Z')), /2026-10-15/);
});
