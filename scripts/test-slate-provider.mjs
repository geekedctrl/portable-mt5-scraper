import assert from 'node:assert/strict';

const host=process.argv[2]||'mt5-market-provider';
const base=`http://${host}:8080/provider/v1`;
async function get(path){
  const response=await fetch(base+path,{signal:AbortSignal.timeout(8000)});
  const body=await response.json();
  assert.equal(response.status,200,`${path}: HTTP ${response.status} ${JSON.stringify(body)}`);
  return body;
}

const specResponse=await fetch(`http://${host}:8080/openapi.json`);
assert.equal(specResponse.status,200,'OpenAPI specification should be available');
const spec=await specResponse.json();
assert.equal(spec.openapi,'3.0.3');
assert.ok(spec.paths['/provider/v1/history/{symbol}']);
const docsResponse=await fetch(`http://${host}:8080/docs`);
assert.equal(docsResponse.status,200,'Swagger UI page should be available');
assert.match(await docsResponse.text(),/swagger-ui/);
for(const asset of ['swagger-ui-bundle.js','swagger-ui.css','swagger-init.js','swagger-overrides.css']){
  const assetResponse=await fetch(`http://${host}:8080/vendor/swagger-ui/${asset}`);
  assert.equal(assetResponse.status,200,`${asset} should be available locally`);
}

const health=await get('/status');
assert.equal(health.provider,'mt5-market-gateway');
assert.equal(health.api_version,'v1');
assert.equal(health.collector?.online,true,'MT5 collector should be online');
assert.equal(health.ready,true,'provider dependencies and workers should be healthy');
assert.ok(health.quote_counts&&Number.isFinite(health.quote_counts.live));
for(const field of ['cycle_duration_ms','mt5_poll_ms','sqlite_write_ms','poll_overruns']){
  assert.ok(Number.isFinite(health.collector?.[field]),`${field} should be reported`);
}

const instruments=await get('/instruments');
assert.ok(instruments.instruments.some((item)=>item.symbol==='EURUSD'),'EURUSD should be subscribed');
const fx=await get('/instruments?asset_class=fx&search=EUR');
assert.ok(fx.instruments.length>0&&fx.instruments.every((item)=>item.asset_class==='fx'&&item.symbol.includes('EUR')),'asset-class/search filters should apply');

const quoteData=await get('/quotes?symbols=EURUSD');
const quoteResult=quoteData.quotes.find((item)=>item.symbol==='EURUSD');
assert.equal(quoteResult?.status,'available');
const quote=quoteResult.quote;
assert.ok(quote,'EURUSD quote should be present');
assert.ok(Number.isFinite(quote.bid)&&quote.bid>0,'bid should be finite and positive');
assert.ok(Number.isFinite(quote.ask)&&quote.ask>=quote.bid,'ask should be ordered and positive');
assert.ok(Number.isFinite(quote.time),'quote should have an epoch timestamp');
assert.ok(Number.isFinite(quote.quoteAgeAtApiMs)&&quote.quoteAgeAtApiMs>=0,'API receipt age should be nonnegative');
assert.ok(['live','stale','warming','offline'].includes(quote.freshness),'freshness should be explicit');
const missing=await get('/quotes?symbols=UNKNOWN');
assert.equal(missing.quotes.length,1);
assert.equal(missing.quotes[0].status,'unavailable');
assert.equal(missing.quotes[0].reason,'not_subscribed');

const history=await get('/history/EURUSD?interval=1m&limit=20');
assert.equal(history.timeframe,'M1');
assert.ok(history.bars.length>0,'stored EURUSD M1 candles should be present');
assert.ok(Number.isFinite(history.coverage.recentBarCount)||history.coverage.recentBarCount===null,'recent bar count should be explicit');
assert.ok(Number.isFinite(history.coverage.start)&&Number.isFinite(history.coverage.end));
for(const bar of history.bars){
  assert.ok(Number.isFinite(bar.time));
  assert.ok(bar.high>=bar.low);
  assert.ok(Number.isFinite(bar.volume));
}

console.log(JSON.stringify({
  network:'reachable',provider:health.provider,collectorOnline:health.collector.online,
  pollIntervalSeconds:health.collector.quote_interval,cycleMs:health.collector.cycle_duration_ms,
  mt5PollMs:health.collector.mt5_poll_ms,sqliteWriteMs:health.collector.sqlite_write_ms,
  pollOverruns:health.collector.poll_overruns,quoteAgeAtApiMs:quote.quoteAgeAtApiMs,
  instruments:instruments.instruments.length,quoteFreshness:quote.freshness,
  historyTimeframe:history.timeframe,bars:history.bars.length,
}));
