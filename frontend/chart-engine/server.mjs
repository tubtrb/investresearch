import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
const routes=new Map([
  ['/',['index.html','text/html; charset=utf-8']], ['/app.mjs',['app.mjs','text/javascript']],
  ['/core.mjs',['core.mjs','text/javascript']], ['/theme.css',['theme.css','text/css']],
  ['/kline.mjs',['node_modules/klinecharts/dist/index.esm.js','text/javascript']],
]);
const port=Number(process.env.PORT??4173);
createServer(async (req,res)=>{
  const file=routes.get(new URL(req.url,'http://localhost').pathname);
  if(!file){res.writeHead(404).end('Not found');return;}
  try {
    const bytes=await readFile(new URL(file[0],import.meta.url));
    res.writeHead(200,{'Content-Type':file[1],'X-Content-Type-Options':'nosniff',
    'Content-Security-Policy':"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}).end(bytes);
  } catch {
    res.writeHead(500).end('Run npm ci before starting the chart.');
  }
}).listen(port,'127.0.0.1',function(){console.log('http://127.0.0.1:'+this.address().port)});
