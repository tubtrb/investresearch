import { init, dispose, getSupportedIndicators, getSupportedOverlays, registerIndicator } from '/kline.mjs';
import { parseCSV,seriesFor,profile,ichimoku,intervals,localParts,marketTimezone,bollinger,atr } from '/core.mjs';
const $=(s)=>document.getElementById(s);
const selectedSeries=new Map();
let rows=[], dataset='가상 예제', chartList=[];
const timeFmt=(time,tz)=>new Intl.DateTimeFormat('ko-KR',{timeZone:tz,dateStyle:'short',timeStyle:'short'}).format(time);
const fmt=(n)=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2}).format(n);
const label={KRX:'한국거래소',NXT:'넥스트레이드',US:'미국',JP:'일본'};
const standard=['VOL','RSI','MACD','KDJ','OBV'];
const indicatorSet=new Set(getSupportedIndicators());
const overlaySet=new Set(getSupportedOverlays());
for(const name of [...indicatorSet].sort())if(!['MA','BOLL',...standard].includes(name))$('extra').add(new Option(name,name));
registerIndicator({name:'IR_BOLL',shortName:'BOLL',series:'price',calcParams:[20,2],
  figures:[{key:'upper',title:'상단 ',type:'line'},{key:'middle',title:'중심 ',type:'line'},{key:'lower',title:'하단 ',type:'line'}],
  calc:(bars,i)=>bollinger(bars,...i.calcParams)});
registerIndicator({name:'IR_ATR',shortName:'ATR',calcParams:[14],figures:[{key:'atr',title:'ATR ',type:'line'}],
  calc:(bars,i)=>atr(bars,i.calcParams[0])});
const phaseLabels={regular:'정규',pre:'프리',post:'애프터'};
registerIndicator({
  name:'IR_ICHIMOKU',shortName:'일목',series:'price',calcParams:[9,26,52,26],precision:2,
  figures:['tenkan','kijun','spanA','spanB','chikou'].map((key,i)=>({key,title:['전환 ','기준 ','선행A ','선행B ','후행 '][i],type:'line'})),
  calc:(data,indicator)=>ichimoku(data,indicator.calcParams),
  draw:({ctx,indicator,visibleRange,xAxis,yAxis})=>{
    const r=indicator.result;
    ctx.save();
    for(let i=Math.max(0,visibleRange.from);i+1<Math.min(visibleRange.to,r.length);i++){
      const a=r[i],b=r[i+1];
      if([a.spanA,a.spanB,b.spanA,b.spanB].some(n=>!Number.isFinite(n)))continue;
      const x0=xAxis.convertToPixel(i),x1=xAxis.convertToPixel(i+1);
      const ya=yAxis.convertToPixel(a.spanA),yb=yAxis.convertToPixel(a.spanB);
      const yc=yAxis.convertToPixel(b.spanA),yd=yAxis.convertToPixel(b.spanB);
      const fill=(points,up)=>{ctx.fillStyle=up?'#39b19b30':'#d76b7730';ctx.beginPath();points.forEach(([x,y],j)=>j?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.fill();};
      const d0=a.spanA-a.spanB,d1=b.spanA-b.spanB;
      if(d0*d1<0){const t=d0/(d0-d1),x=x0+t*(x1-x0),y=ya+t*(yc-ya);
        fill([[x0,ya],[x,y],[x0,yb]],d0>0);fill([[x,y],[x1,yc],[x1,yd]],d1>0);
      }else fill([[x0,ya],[x1,yc],[x1,yd],[x0,yb]],d0+d1>=0);
    }
    ctx.restore();return false;
  },
});
for(const tf of intervals){const opt=new Option(({D:'일봉',W:'주봉',M:'월봉'}[tf]??tf.replace('m','분봉')),tf);$('interval').add(opt);}
$('interval').value='D';
function demo() {
  const bars=[];
  for(const [symbol,name,market,currency,start] of [['KOSPI','코스피 예제','KRX','포인트',2600],['000660','하이닉스 예제','KRX','KRW',140000],['005930','삼성전자 예제','KRX','KRW',60000],['263750','펄어비스 예제','KRX','KRW',42000]]){
    let p=start;
    for(let i=0;i<1000;i++){
      const t=Date.UTC(2024,0,2+i,6,30);
      const day=new Date(t).getUTCDay();if(day===0||day===6)continue;
      const open=p, close=Math.max(1,p*(1+.009*Math.sin(i*.49+start)+.004*Math.sin(i*.05)+.0008));p=close;
      bars.push({symbol,name,market,currency,session:'regular',resolution:'D',timestamp:t,open,close,high:Math.max(open,close)*1.009,low:Math.min(open,close)*.992,volume:symbol==='KOSPI'?null:Math.round(400000*(1+Math.sin(i*.8)**2))});
    }
  }
  for(let i=0;i<390;i++){
    const timestamp=Date.UTC(2026,8,24,0,i),open=48000+100*Math.sin(i*.025),close=open+60*Math.sin(i*.79);
    bars.push({symbol:'263750',name:'펄어비스 예제',market:'KRX',currency:'KRW',session:'regular',resolution:'1m',timestamp,open,close,high:Math.max(open,close)+25,low:Math.min(open,close)-25,volume:100+i%61});
  }
  return bars.sort((a,b)=>a.timestamp-b.timestamp);
}
function load(data,name) {
  if(!data.length)throw new Error('데이터 행이 없습니다.');
  rows=data;dataset=name;selectedSeries.clear();$('symbol').replaceChildren();
  for(const b of data){
    const k=b.symbol+' · '+b.market;
    if(!selectedSeries.has(k)){selectedSeries.set(k,b);$('symbol').add(new Option(b.name+' · '+b.market,k));}
  }
  $('source').textContent=(name==='가상 예제'?'가상 예제 · 실거래가 아님':'사용자 제공 파일 · ')+name;
  redraw();
}
function selected() {
  const key=$('symbol').value;
  const keys=[...selectedSeries.keys()];
  return $('compare').checked?(keys.length<=4?keys:[key,...keys.filter(k=>k!==key)].slice(0,4)):[key];
}
function selectData(series,clip) {
  if(clip==='all'||!series.length)return series;
  if(clip==='100')return series.slice(-100);
  return series.filter(b=>localParts(b.timestamp,clip).year===localParts(series.at(-1).timestamp,clip).year);
}
function redraw(){
  const tf=$('interval').value, phase=$('session').value;
  const ma=$('ma').value.trim().split(',').filter(Boolean).map(Number);
  if(ma.some(n=>!Number.isInteger(n)||n<1||n>300)||ma.length>6||new Set(ma).size!==ma.length){$('status').textContent='이동평균은 1–300 사이의 서로 다른 정수 최대 6개를 쉼표로 구분하세요.';return;}
  for(const x of chartList)if(x.chart)dispose(x.container);
  chartList=[]; $('panels').replaceChildren();$('target').replaceChildren();
  const warnings=[];
  for(const key of selected()){
    const meta=selectedSeries.get(key),tz=marketTimezone[meta.market];
    const data=seriesFor(rows,{symbol:meta.symbol,market:meta.market,session:phase,interval:tf});
    const rawProfile=seriesFor(rows,{symbol:meta.symbol,market:meta.market,session:phase,interval:tf.endsWith('m')?'1m':'D'});
    const visible=selectData(data,$('range').value==='ytd'?tz:$('range').value);
    const article=document.createElement('article');article.className='panel';
    const title=document.createElement('h2');title.textContent=meta.name+' · '+label[meta.market]+' · '+phaseLabels[phase]+' · '+meta.currency;article.append(title);
    const info=document.createElement('div');info.className='details';article.append(info);$('panels').append(article);
    if(!data.length){info.textContent='이 거래소·세션·주기의 입력 바가 없습니다. 분봉은 1분봉 CSV가 필요합니다.';continue;}
    const row=document.createElement('div');row.className='chartrow';
    const container=document.createElement('div');container.className='chart';row.append(container);article.append(row);
    const chart=init(container,{styles:'dark'});
    if(!chart){warnings.push('차트 초기화 실패: '+key);continue;}
    chartList.push({chart,container,key});$('target').add(new Option(meta.name,key));
    chart.setTimezone(tz);
    const digits=['JPY','KRW'].includes(meta.currency)?0:2;
    chart.setPriceVolumePrecision(digits,0);
    chart.setStyles({candle:{type:$('type').value,bar:{upColor:'#ef7474',downColor:'#62a7ff',noChangeColor:'#acbec6',upBorderColor:'#ef7474',downBorderColor:'#62a7ff',noChangeBorderColor:'#acbec6',upWickColor:'#ef7474',downWickColor:'#62a7ff',noChangeWickColor:'#acbec6'}}});
    const last=data.at(-1);
    const confirmed=last.provisional?rawProfile.findLast(b=>!b.provisional):null;
    const estimate=last.provisional?' · 분봉 집계 잠정값'+(confirmed?' (마지막 확정 일봉 '+timeFmt(confirmed.asOf,tz)+' · '+fmt(confirmed.close)+')':''):'';
    info.textContent=timeFmt(last.asOf,tz)+' 기준 · '+(last.provisional?'최종 관측가 ':'종가 ')+fmt(last.close)+' · '+visible.length+'봉'+estimate+(['W','M'].includes(tf)?' · 마지막 봉 진행 중일 수 있음':'');
    chart.applyNewData(data.map(x=>({...x,volume:x.volume??undefined})),false);
    if($('range').value!=='all'&&visible.length>0&&visible.length<data.length)chart.setBarSpace(Math.max(1,Math.min(50,Math.max(200,container.clientWidth-95)/visible.length)));
    if(ma.length)chart.createIndicator({name:'MA',calcParams:ma},true,{id:'candle_pane'});
    if($('boll').checked&&data.length>=20)chart.createIndicator({name:'IR_BOLL',calcParams:[20,2]},true,{id:'candle_pane'});
    if($('cloud').checked&&data.length>=26)chart.createIndicator('IR_ICHIMOKU',true,{id:'candle_pane'});
    for(const ind of standard)if($(ind.toLowerCase()).checked&&indicatorSet.has(ind)&&(!['VOL','OBV'].includes(ind)||data.every(x=>x.volume!=null)))chart.createIndicator(ind,false,{height:85});
    if($('atr').checked)chart.createIndicator('IR_ATR',false,{height:85});
    if($('extra').value)chart.createIndicator($('extra').value,false,{height:85});
    if($('profile').checked){
      const side=document.createElement('aside');side.className='profile';const h=document.createElement('strong');h.textContent='매물대 · 선택 조회 구간';side.append(h);
      const bins=profile(rawProfile.filter(x=>x.timestamp>=visible[0].timestamp),12);
      if(!bins.length){const p=document.createElement('p');p.textContent='거래량 없음';side.append(p);}
      for(const b of [...bins].reverse()){
        const p=document.createElement('p');
        p.style.setProperty('--w',100*b.share/Math.max(...bins.map(x=>x.share))+'%');
        p.textContent=fmt(b.low)+'–'+fmt(b.high)+' '+(100*b.share).toFixed(1)+'%';side.append(p);
      }
      row.append(side);chart.resize();
    }
    if($('boll').checked&&data.length<20)warnings.push(meta.name+' 볼린저: 20봉 미만');
    if($('cloud').checked&&data.length<78)warnings.push(meta.name+' 일목: 구름 데이터 일부 부족');
  }
  $('status').textContent=warnings.join(' · ');$('draw').value='';
}
for(const id of ['symbol','session','interval','type','range','compare','ma','boll','cloud','vol','profile','rsi','macd','kdj','atr','obv','extra'])$(id).addEventListener('change',redraw);
const active=()=>chartList.find(x=>x.key===$('target').value)?.chart;
$('draw').addEventListener('change',()=>{
  const name=$('draw').value, chart=active();
  if(!name||!chart)return;
  if(!overlaySet.has(name)){$('status').textContent='이 그리기 도구는 지원되지 않습니다.';return;}
  chart.createOverlay(name,'candle_pane');$('status').textContent='가격 패널을 클릭해 점을 지정하세요.';$('draw').value='';
});
$('clear').addEventListener('click',()=>active()?.removeOverlay());
$('png').addEventListener('click',()=>{const chart=active();if(!chart)return;const a=document.createElement('a');a.download='investresearch-chart.png';a.href=chart.getConvertPictureUrl(true,'png','#172634');a.click();});
$('demo').addEventListener('click',()=>load(demo(),'가상 예제'));
$('file').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>16_000_000)throw new Error('CSV는 16MB 이하만 불러올 수 있습니다.');load(parseCSV(await file.text()),file.name);}catch(e){$('status').textContent=e.message;}finally{event.target.value='';}});
window.addEventListener('resize',()=>chartList.forEach(x=>x.chart?.resize()));
load(demo(),'가상 예제');
