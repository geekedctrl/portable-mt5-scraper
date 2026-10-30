const test = require('node:test');
const assert = require('node:assert/strict');
require('../dashboard/static/chart_paging.js');

const { ChartPaging } = globalThis;

test('drag direction maps rightward movement to older candles', () => {
  assert.equal(ChartPaging.dragDelta(10, 35), 25);
  assert.equal(ChartPaging.dragDelta(35, 10), -25);
});

test('pointer cancellation ends only the captured gesture', () => {
  const active = { id: 7 };
  assert.equal(ChartPaging.endGesture(active, 7), null);
  assert.equal(ChartPaging.endGesture(active, 8), active);
});

test('horizontal wheel pans and Ctrl+wheel remains available to browser zoom', () => {
  assert.equal(ChartPaging.wheelDelta(14, false), 14);
  assert.equal(ChartPaging.wheelDelta(14, true), 0);
});

test('older-page merge sorts and deduplicates without losing the viewport anchor', () => {
  const current = [{ time: 20, close: 2 }, { time: 30, close: 3 }];
  const merged = ChartPaging.mergeOlder(current, [{ time: 10, close: 1 }, { time: 20, close: 22 }]);
  assert.deepEqual(merged.map(bar => bar.time), [10, 20, 30]);
  assert.equal(merged[1].close, 22);
  assert.equal(ChartPaging.preserveAnchor(12, 2), 14);
});

test('preload threshold requires older history and uses one fifth of the visible count', () => {
  assert.equal(ChartPaging.needsOlder(40, 200, true), true);
  assert.equal(ChartPaging.needsOlder(41, 200, true), false);
  assert.equal(ChartPaging.needsOlder(0, 200, false), false);
});
