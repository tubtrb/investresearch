export const intervals = ['1m','5m','15m','30m','60m','D','W','M'];
export const sessions = ['KRX','NXT','US','JP'];
const phases = ['regular','pre','post'];
const offsets = new Map();
function formatter(tz) {
  if (!offsets.has(tz)) offsets.set(tz,new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}));
  return offsets.get(tz);
}
export function localParts(timestamp,tz) {
  return Object.fromEntries(formatter(tz).formatToParts(timestamp).filter(p=>p.type!=='literal').map(p=>[p.type,Number(p.value)]));
}
function tradingDay(timestamp,tz,tf,phase) {
  const {year,month,day,hour,minute}=localParts(timestamp,tz);
  const date=Date.UTC(year,month-1,day);
  if(tf==='D') return date;
  if(tf==='W') return date-((new Date(date).getUTCDay()+6)%7)*86400000;
  if(tf==='M') return Date.UTC(year,month-1,1);
  const n=Number(tf.slice(0,-1));
  // Anchor known regular sessions to the exchange open, not midnight.
  const open=phase==='regular'?(tz==='America/New_York'?570:540):0;
  const minutes=hour*60+minute;
  return minutes<open?null:date+(open+Math.floor((minutes-open)/n)*n)*60000;
}
const iso=/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,3})?)?(?:Z|[+-]\d\d:\d\d)$/;
const number=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
export function parseCSV(text) {
  const source=text.replace(/^\uFEFF/,'').trim();
  if(!source)throw new Error('CSV가 비어 있습니다.');
  const [header,...lines]=source.split(/\r?\n/);
  const keys=header.toLowerCase().split(',').map(s=>s.trim());
  const required=['symbol','timestamp','open','high','low','close','volume','market','session','resolution'];
  if(new Set(keys).size!==keys.length||required.some(k=>!keys.includes(k)))throw new Error('CSV 헤더가 빠졌거나 중복되었습니다.');
  const seen=new Set();
  const securityMeta=new Map();
  return lines.filter(line=>line.trim()).map((line,i)=>{
    const fields=line.split(',').map(s=>s.trim());
    const r=Object.fromEntries(keys.map((k,j)=>[k,fields[j]??'']));
    const timestamp=Date.parse(r.timestamp);
    const nums=['open','high','low','close','volume'].map(k=>r[k]===''&&k==='volume'?null:number.test(r[k])?Number(r[k]):NaN);
    const [open,high,low,close,volume]=nums;
    const market=r.market.toUpperCase();
    const stamp=r.resolution==='D'&&sessions.includes(market)&&Number.isFinite(timestamp)?tradingDay(timestamp,marketTimezone[market],'D',r.session):timestamp;
    const id=[r.symbol,market,r.session,r.resolution,stamp].join('|');
    if(fields.length!==keys.length||!r.symbol||!iso.test(r.timestamp)||!Number.isFinite(timestamp)||
       nums.some(v=>v!==null&&!Number.isFinite(v))||low<=0||low>Math.min(open,close)||high<Math.max(open,close)||volume<0||
       !sessions.includes(market)||!phases.includes(r.session)||!['1m','D'].includes(r.resolution)||
       (r.resolution==='D'&&r.session!=='regular')||seen.has(id)) throw new Error('CSV '+(i+2)+'행 형식 또는 중복 오류');
    seen.add(id);
    const name=r.name||r.symbol;
    const currency=r.currency||({KRX:'KRW',NXT:'KRW',US:'USD',JP:'JPY'}[market]);
    const metaKey=[r.symbol,market].join('|');
    const prev=securityMeta.get(metaKey);
    if(prev && prev!==JSON.stringify([name,currency]))throw new Error('CSV '+(i+2)+'행 종목 정보 불일치');
    securityMeta.set(metaKey,JSON.stringify([name,currency]));
    return {symbol:r.symbol,name,currency,timestamp,open,high,low,close,volume,market,session:r.session,resolution:r.resolution};
  }).sort((a,b)=>a.timestamp-b.timestamp);
}
export const marketTimezone={KRX:'Asia/Seoul',NXT:'Asia/Seoul',US:'America/New_York',JP:'Asia/Tokyo'};
export function seriesFor(rows,{symbol,market,session='regular',interval='D'}) {
  if(!intervals.includes(interval)||!sessions.includes(market)||!phases.includes(session))throw new Error('지원하지 않는 시장·주기');
  const min=interval.endsWith('m');
  const bars=rows.filter(x=>x.symbol===symbol&&x.market===market&&x.session===session);
  const tz=marketTimezone[market];
  const minutes=bars.filter(x=>x.resolution==='1m');
  if(min)return aggregate(minutes,interval,tz,session);
  const byDate=new Map();
  for(const day of aggregate(minutes,'D',tz,session)){
    byDate.set(tradingDay(day.timestamp,tz,'D',session),{...day,provisional:true});
  }
  for(const day of bars.filter(x=>x.resolution==='D')){
    const key=tradingDay(day.timestamp,tz,'D',session);
    if(byDate.get(key)?.resolution==='D')throw new Error('종목별 거래일에 일봉이 둘 이상입니다.');
    byDate.set(key,{...day,provisional:false});
  }
  return aggregate([...byDate.values()],interval,tz,session);
}
export function aggregate(rows,interval,tz,phase='regular') {
  const result=[];
  let prev=null,key0=null;
  for(const x of [...rows].sort((a,b)=>a.timestamp-b.timestamp)) {
    if(interval.endsWith('m')&& x.resolution!=='1m')continue;
    const key=tradingDay(x.timestamp,tz,interval,phase);
    if(key===null)continue;
    if(prev&&key===key0) {
      prev.high=Math.max(prev.high,x.high);prev.low=Math.min(prev.low,x.low);prev.close=x.close;
      prev.volume=prev.volume==null||x.volume==null?null:prev.volume+x.volume;
      prev.asOf=x.asOf??x.timestamp;
      prev.provisional=prev.provisional||Boolean(x.provisional);
    } else {
      prev={timestamp:x.timestamp,asOf:x.asOf??x.timestamp,provisional:Boolean(x.provisional),open:x.open,high:x.high,low:x.low,close:x.close,volume:x.volume};
      result.push(prev);key0=key;
    }
  }
  return result;
}
export function profile(bars,bins=24) {
  if(!Number.isInteger(bins)||bins<1||bins>200)throw new Error('매물대 구간 수 오류');
  const used=bars.filter(x=>Number.isFinite(x.volume)&&x.volume>0);
  if(!used.length)return [];
  const low=used.reduce((m,x)=>Math.min(m,x.low),Infinity), high=used.reduce((m,x)=>Math.max(m,x.high),-Infinity);
  if(low===high)return [{low,high,volume:used.reduce((a,x)=>a+x.volume,0),share:1}];
  const width=(high-low)/bins;
  const out=Array.from({length:bins},(_,i)=>({low:low+width*i,high:i===bins-1?high:low+width*(i+1),volume:0}));
  const total=used.reduce((a,x)=>a+x.volume,0);
  for(const bar of used) {
    if(bar.low===bar.high){out[Math.max(0,Math.min(bins-1,Math.floor((bar.low-low)/width)))].volume+=bar.volume;continue;}
    for(const bin of out)bin.volume+=bar.volume*Math.max(0,Math.min(bin.high,bar.high)-Math.max(bin.low,bar.low))/(bar.high-bar.low);
  }
  return out.map(bin=>({...bin,share:bin.volume/total}));
}
export function bollinger(bars,n=20,k=2) {
  return bars.map((_,i)=>{
    if(i+1<n)return {};
    const prices=bars.slice(i-n+1,i+1).map(b=>b.close);
    const middle=prices.reduce((a,b)=>a+b,0)/n;
    const sd=Math.sqrt(prices.reduce((a,b)=>a+(b-middle)**2,0)/n);
    return {middle,upper:middle+k*sd,lower:middle-k*sd};
  });
}
export function ichimoku(bars,[fast,slow,long,shift]=[9,26,52,26]) {
  const out=bars.map(()=>({}));
  const midpoint=(i,n)=>{
    if(i+1<n)return;
    const w=bars.slice(i-n+1,i+1);
    return (Math.max(...w.map(x=>x.high))+Math.min(...w.map(x=>x.low)))/2;
  };
  for(let i=0;i<bars.length;i++) {
    const tenkan=midpoint(i,fast),kijun=midpoint(i,slow), spanB=midpoint(i,long);
    out[i].tenkan=tenkan;out[i].kijun=kijun;
    if(i+shift<bars.length){out[i+shift].spanA=tenkan===undefined||kijun===undefined?undefined:(tenkan+kijun)/2;out[i+shift].spanB=spanB;}
    if(i>=shift)out[i-shift].chikou=bars[i].close;
  }
  return out;
}

export function atr(bars,n=14) {
  let total=0, prev;
  return bars.map((x,i)=>{
    const old=bars[i-1]?.close;
    const tr=i===0?x.high-x.low:Math.max(x.high-x.low,Math.abs(x.high-old),Math.abs(x.low-old));
    if(i<n)total+=tr;
    if(i===n-1)prev=total/n;
    else if(i>=n)prev=(prev*(n-1)+tr)/n;
    return {atr:prev};
  });
}
