import {readFile,writeFile,mkdir} from 'node:fs/promises';
const read=path=>readFile(new URL(path,import.meta.url),'utf8');
const jsString=s=>JSON.stringify(s).replace(/</g,'\\u003c');
const [page,style,core,app,lib,...licenses]=await Promise.all(['index.html','theme.css','core.mjs','app.mjs','node_modules/klinecharts/dist/index.esm.js','node_modules/klinecharts/NOTICE','node_modules/klinecharts/LICENSE','node_modules/klinecharts/licenses/LICENSE-lightweight-charts'].map(read));
const legal='<details><summary>오픈소스 라이선스</summary><pre style="white-space:pre-wrap">'+licenses.join('\n\n').replaceAll('&','&amp;').replaceAll('<','&lt;')+'</pre></details>';
const boot=`<script type="module">
const mod=s=>URL.createObjectURL(new Blob([s],{type:'text/javascript'}));
const core=mod(${jsString(core)});
const vendor=mod(${jsString(lib)});
const app=${jsString(app)}.replaceAll("'/core.mjs'",JSON.stringify(core)).replaceAll("'/kline.mjs'",JSON.stringify(vendor));
await import(mod(app));
</script>`;
await mkdir(new URL('dist/',import.meta.url),{recursive:true});
await writeFile(new URL('dist/InvestResearch-chart-engine-v0.1.0.html',import.meta.url),page.replace('<link rel="stylesheet" href="/theme.css">',`<style>${style}</style>`).replace('</footer>','</footer>'+legal).replace('<script type="module" src="/app.mjs"></script>',boot),'utf8');
