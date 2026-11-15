import assert from 'node:assert/strict';
import test from 'node:test';
import { readLimitedBody, BodyTooLargeError } from '../lib/request-body.ts';

test('body limits count UTF-8 bytes and accept the exact boundary', async () => {
  const make = () => new Request('https://example.test', { method: 'POST', body: '错' });
  assert.equal(await readLimitedBody(make(), 3), '错');
  await assert.rejects(readLimitedBody(make(), 2), BodyTooLargeError);
});
test('oversize streams without content length are cancelled before buffering more', async () => {
  let cancelled = false;
  const body = new ReadableStream({ pull(c) { c.enqueue(new Uint8Array(10)); }, cancel() { cancelled = true; } });
  await assert.rejects(readLimitedBody(new Request('https://example.test', { method: 'POST', body, duplex: 'half' }), 15), BodyTooLargeError);
  assert.equal(cancelled, true);
});
test('declared oversize is rejected before reading and invalid UTF-8 is rejected', async () => {
  await assert.rejects(readLimitedBody(new Request('https://example.test', { method: 'POST', body: 'x', headers: { 'content-length': '100' } }), 10), BodyTooLargeError);
  await assert.rejects(readLimitedBody(new Request('https://example.test', { method: 'POST', body: new Uint8Array([255]) }), 10), TypeError);
});
