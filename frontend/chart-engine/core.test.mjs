import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseCSV,seriesFor,aggregate,profile,bollinger,ichimoku,atr} from './core.mjs';
import * as lib from './node_modules/klinecharts/dist/index.esm.js';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
const h='symbol,timestamp,open,high,low,close,volume,market,session,resolution';
const d=['X,2026-11-23T15:30+09:00,100,120,90,115,10,KRX,regular,D',
'X,2026-11-24T15:30+09:00,115,125,110,120,20,KRX,regular,D',
'X,2026-11-24T15:31+09:00,120,135,115,130,99,NXT,regular,D',
'X,2026-11-24T09:00+09:00,102,105,101,104,3,KRX,regular,1m',
'X,2026-11-24T09:04+09:00,104,109,103,106,4,KRX,regular,1m',
'X,2026-11-24T09:05+09:00,106,110,102,103,5,KRX,regular,1m'];
const make=(xs)=>parseCSV([h,...xs].join('\n'));
test('weekly and monthly OHLCV; daily source wins; venue boundaries',()=>{
 const a=make(d);
 for(const interval of ['W','M']) {
  const [b]=seriesFor(a,{symbol:'X',market:'KRX',interval});assert.deepEqual([b.open,b.high,b.low,b.close,b.volume],[100,125,90,120,30]);
 }
 assert.equal(seriesFor(a,{symbol:'X',market:'NXT'})[0].close,130);
 assert.equal(seriesFor(a,{symbol:'X',market:'NXT',session:'post'}).length,0);
 assert.equal(seriesFor(a,{symbol:'X',market:'NXT',interval:'5m'}).length,0);
});
test('5-minute bucketing and missing-volume propagation',()=>{
 const [a,b]=seriesFor(make(d),{symbol:'X',market:'KRX',interval:'5m'});assert.deepEqual([a.open,a.high,a.low,a.close,a.volume],[102,109,101,106,7]);assert.equal(b.close,103);
 const z=make([d[0],d[1].replace(',20,',',,')]);assert.equal(seriesFor(z,{symbol:'X',market:'KRX',interval:'M'})[0].volume,null);
});
test('US 60-minute bars start at 09:30 local in standard time and DST',()=>{
 for(const [date,hour] of [['2026-11-25',14],['2026-07-13',13]]) {
  const xs=['30','59','60'].map((m,i)=>({resolution:'1m',timestamp:Date.UTC(...date.split('-').map((v,j)=>+v-(j===1?1:0)),hour,30+i*30),open:1,high:1,low:1,close:1,volume:1}));
  assert.deepEqual(aggregate(xs,'60m','America/New_York').map(b=>b.volume),[2,1]);
 }
});
test('CSV rejects duplicates, invalid data, out-of-market and ambiguous local time',()=>{
 for(const r of [d[0].replace('120,90','99,90'),d[0].replace('+09:00',''),d[0].replace(',10,',',-2,'),d[0].replace('KRX','XYZ')])assert.throws(()=>make([r]));
 assert.throws(()=>make([d[0],d[0]]),/중복/);
});
test('volume is conserved, missing volume is not counted and point bar lands in final bin',()=>{
 const bins=profile([{low:0,high:4,volume:20},{low:2,high:4,volume:8},{low:4,high:4,volume:4},{low:0,high:4,volume:null}],4);
 assert.deepEqual(bins.map(x=>x.volume),[5,5,9,13]);assert.equal(bins.reduce((a,b)=>a+b.share,0),1);
 assert.deepEqual(profile([{low:1,high:2,volume:null}]),[]);
});
test('Bollinger uses population variance, ATR uses Wilder smoothing, cloud shifts',()=>{
 const b=[1,2,3].map(x=>({close:x,high:x+1,low:x-1}));
 assert.deepEqual(bollinger(b,2,2).map(x=>x.middle),[undefined,1.5,2.5]);
 assert.equal(bollinger(b,2,2)[1].upper,2.5);
 const xs=Array.from({length:80},(_,i)=>({low:i+1,high:i+3,close:i+2}));
 assert.equal(ichimoku(xs)[76].spanB,undefined);assert.equal(ichimoku(xs)[77].spanB,27.5);assert.equal(ichimoku(xs)[0].chikou,28);
 assert.deepEqual(atr(b,2).map(x=>x.atr),[undefined,2,2]);
});
test('Pinned chart module exposes needed indicators, overlays and chart enums',()=>{
 for(const n of ['MA','VOL','RSI','MACD','KDJ','OBV'])assert.ok(lib.getSupportedIndicators().includes(n));
 for(const n of ['horizontalStraightLine','verticalStraightLine','segment','rayLine','priceLine','fibonacciLine','parallelStraightLine'])assert.ok(lib.getSupportedOverlays().includes(n));
 assert.equal(lib.version(),'9.8.12');
});
test('Browser entry point serves local chart JS, dependencies, CSP and rejects unknown paths',async()=>{
 const child=spawn(process.execPath,['server.mjs'],{env:{...process.env,PORT:'0'}});
 try {
  const [startup]=await once(child.stdout,'data');
  const port=String(startup).trim().split(':').at(-1);
  const u='http://127.0.0.1:'+port;
  const files=await Promise.all(['/','/app.mjs','/core.mjs','/kline.mjs','/theme.css'].map(x=>fetch(u+x)));
  assert.ok(files.every(x=>x.ok));
  assert.match(await files[0].text(),/독립 차트 엔진/);
  assert.match(files[0].headers.get('content-security-policy'),/default-src 'self'/);
  assert.equal((await fetch(u+'/package.json')).status,404);
 }finally{child.kill();}
});
