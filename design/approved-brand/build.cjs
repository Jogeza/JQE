const fs=require('fs'), path=require('path');
const sharp=require('C:/Users/moses/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const qrcode=require('../flyer-templates-v2/node_modules/qrcode-generator');
const jsQR=require('../flyer-templates-v2/node_modules/jsqr');
const out=__dirname;
const logo=fs.readFileSync(path.join(out,'weltrade-logo-original.svg'),'utf8');
const logoInner=logo.slice(logo.indexOf('>')+1,logo.lastIndexOf('</svg>'));
const brand=`<g id="01_Brand_Logos"><g id="JQE_site_lockup"><path d="M64 88h12l8-18 12 36 8-18h12" fill="none" stroke="#f3f2eb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><text x="127" y="105" font-family="Arial" font-size="48" font-weight="800" letter-spacing="-3" fill="#f3f2eb">JQE</text><text x="226" y="103" font-family="Arial" font-size="24" font-weight="700" fill="#d3e8a0">Quant</text></g><path d="M327 64v48" stroke="#547066"/><rect x="354" y="60" width="225" height="58" fill="#17352e"/><svg x="368" y="69" width="198" height="41" viewBox="0 0 170 35">${logoInner}</svg></g>`;
const ink='#081d17',paper='#f6f4ea',lime='#d3e8a0',muted='#b5c5b7';
const escape=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
const t=(x,y,s,size=24,color=paper,weight=400,attrs='')=>`<text x="${x}" y="${y}" font-family="Arial" font-size="${size}" font-weight="${weight}" fill="${color}" ${attrs}>${escape(s)}</text>`;
const rule=(x,y,w,color=lime)=>`<path d="M${x} ${y}h${w}" stroke="${color}" stroke-width="2"/>`;
const urls={website:'https://jqe.jokiholdings.com',telegram:'https://t.me/jqetrading'};
const designs=[
 {file:'01-editorial',label:'01 / BRAND EDITORIAL',photo:'market',layout:'hero',heading:['Look closer.','See clearer.'],detail:'Your market. A fresh perspective.',sub:'Analysis, research and journaling for Weltrade synthetic indices.',cta:'Explore JQE.'},
 {file:'02-research',label:'02 / RESEARCH',photo:'research',layout:'column',heading:['Put research','at the','centre.'],detail:'Observe. Test. Review.',sub:'Explore market ideas with a more considered process.',cta:'Explore the workspace.'},
 {file:'03-campaign',label:'03 / PRODUCT INTRODUCTION',photo:'research',layout:'centre',heading:['Meet your new','perspective.'],detail:'One workspace. A clearer process.',sub:'Market analysis. Historical research. Decision journaling.',cta:'Meet JQE.'},
 {file:'04-photo-led',label:'04 / DECISION JOURNAL',photo:'journal',layout:'journal',heading:['Every decision','has a story.'],detail:'Keep the context. Record the reasoning.',sub:'Bring your observations together in the JQE decision journal.',cta:'Make room for reflection.'},
 {file:'05-background-editorial',label:'05 / MARKET ANALYSIS',photo:'market',layout:'bottom',heading:['Read the','bigger picture.'],detail:'Price. Context. Perspective.',sub:'Explore Weltrade synthetic indices with JQE.',cta:'Take a closer look.'},
 {file:'06-telegram',label:'06 / TELEGRAM COMMUNITY',photo:'journal',layout:'community',heading:['Good questions.','Shared perspective.'],detail:'Follow the JQE conversation.',sub:'Stay connected with @jqetrading on Telegram.',cta:'Join us on Telegram.'}
];
function qr(url,x,y,size=136){const q=qrcode(0,'M');q.addData(url);q.make();const n=q.getModuleCount();let p='';for(let row=0;row<n;row++)for(let col=0;col<n;col++)if(q.isDark(row,col))p+=`M${col+4} ${row+4}h1v1h-1z`;return `<g transform="translate(${x} ${y}) scale(${size/(n+8)})"><rect width="${n+8}" height="${n+8}" fill="white"/><path d="${p}" fill="#111"/></g>`;}
function footer(d,H){return `<g id="06_Editable_Contact">${rule(64,H-252,952,'#52685c')}${t(64,H-201,d.cta,34,paper,700)}${t(64,H-151,'jqe.jokiholdings.com',27,paper,700)}${t(64,H-110,'Telegram / @jqetrading',24)}${t(64,H-76,d.layout==='community'?'Scan TELEGRAM to join the channel.':'Scan to explore. Stay connected.',18,muted)}</g><g id="07_QR_Codes">${qr(urls.website,724,H-223)}${qr(urls.telegram,884,H-223)}${t(792,H-62,'WEBSITE',14,paper,700,'text-anchor="middle" letter-spacing="1"')}${t(952,H-62,'TELEGRAM',14,paper,700,'text-anchor="middle" letter-spacing="1"')}</g><g id="08_Editable_Product_Footer">${t(64,H-28,'Demo research platform. Trading involves risk. No guaranteed returns.',16,muted)}</g>`;}
function content(d,H){
 const extra=H-1350;
 let text='',art='';
 const eyebrow=t(64,184,d.label,17,lime,700,'letter-spacing="2"');
 const headline=(x,start,size,leading,center=false)=>d.heading.map((s,i)=>t(x,start+i*leading,s,size,i===d.heading.length-1?lime:paper,700,`letter-spacing="-3" ${center?'text-anchor="middle"':''}`)).join('');
 if(d.layout==='hero')text=eyebrow+headline(58,280,100,103);
 if(d.layout==='column'){
  art=`<rect x="0" y="160" width="635" height="${H-160}" fill="${ink}" opacity=".62"/><path d="M625 188v${H-530}" stroke="${lime}" stroke-opacity=".45"/>`;
  text=eyebrow+headline(59,288,81,91)+rule(64,613,64)+t(64,680,'01 / Study the context',26,paper,700)+t(64,730,'02 / Explore an idea',26,paper,700)+t(64,780,'03 / Review the evidence',26,paper,700);
 }
 if(d.layout==='centre'){
  text=t(540,185,d.label,17,lime,700,'text-anchor="middle" letter-spacing="2"')+headline(540,289,88,99,true)+rule(428,430,224);
 }
 if(d.layout==='journal'){
  text=eyebrow+headline(86,286,90,102);
  art=`<path d="M64 223v184" stroke="${lime}" stroke-width="3"/>`;
 }
 if(d.layout==='bottom'){
  text=eyebrow+t(64,235,'JQE / Research & perspective',25,paper)+headline(59,H-592,94,105);
 }
 if(d.layout==='community'){
  text=eyebrow+t(64,247,'@jqetrading',46,paper,700)+headline(59,H-565,81,94);
  art=rule(64,281,105);
 }
 text+=rule(64,H-403,55)+t(64,H-347,d.detail,d.layout==='journal'?32:34,paper,700)+t(64,H-303,d.sub,22,'#dde5d9');
 return `<g id="04_Layout_Accents">${art}</g><g id="05_Editable_Headline_and_Benefits">${text}</g>`;
}
async function make(d,a4){
 const H=a4?1527.428571:1350;
 const photo=fs.readFileSync(path.join(out,`photo-${d.photo}.png`)).toString('base64');
 const bottomStart=['bottom','community'].includes(d.layout)?'.40':'.59';
 const topFade=['column','journal'].includes(d.layout)?'.42':'.31';
 const defs=`<defs><linearGradient id="top" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${ink}" stop-opacity=".94"/><stop offset="${topFade}" stop-color="${ink}" stop-opacity=".68"/><stop offset=".51" stop-color="${ink}" stop-opacity="0"/></linearGradient><linearGradient id="bottom" x1="0" y1="0" x2="0" y2="1"><stop offset="${bottomStart}" stop-color="${ink}" stop-opacity="0"/><stop offset=".73" stop-color="${ink}" stop-opacity=".88"/><stop offset="1" stop-color="${ink}" stop-opacity="1"/></linearGradient></defs>`;
 const svg=`<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="${a4?'210mm':'1080'}" height="${a4?'297mm':H}" viewBox="0 0 1080 ${H}"><title>${d.label} — JQE approved branding</title><desc>Editable text, vector logos and QR codes, embedded AI illustrative photo. Interface is conceptual. RGB, no bleed.</desc>${defs}<g id="02_Full_Background_Photo"><image width="1080" height="${H}" preserveAspectRatio="xMidYMid slice" href="data:image/png;base64,${photo}"/></g><g id="03_Readability_Overlays"><rect width="1080" height="${H}" fill="url(#top)"/><rect width="1080" height="${H}" fill="url(#bottom)"/></g>${brand}${content(d,H)}${footer(d,H)}</svg>`;
 const name=`${d.file}-${a4?'a4':'social'}`;
 fs.writeFileSync(path.join(out,name+'.svg'),svg);
 await sharp(Buffer.from(svg)).resize(a4?1080:1080,Math.round(H)).png().toFile(path.join(out,name+'-preview.png'));
 await sharp(Buffer.from(svg)).resize(a4?2160:1080,a4?3055:1350).png().toFile(path.join(out,name+'-export.png'));
 const raw=await sharp(Buffer.from(svg)).resize(1080,Math.round(H)).ensureAlpha().raw().toBuffer({resolveWithObject:true});
 for(const [kind,x] of [['website',724],['telegram',884]]){
  const b=await sharp(raw.data,{raw:raw.info}).extract({left:x,top:Math.round(H-223),width:136,height:136}).resize(544,544,{kernel:'nearest'}).raw().toBuffer();
  if(jsQR(new Uint8ClampedArray(b),544,544)?.data!==urls[kind])throw Error(`QR failed ${name} ${kind}`);
 }
 return `${name}: website and Telegram QR codes decoded correctly.`;
}
async function main(){
 const results=[];for(const d of designs)for(const a4 of [true,false])results.push(await make(d,a4));
 const tiles=[];
 for(let i=0;i<designs.length;i++){
  const png=await sharp(path.join(out,designs[i].file+'-a4-preview.png')).resize(360,509).toBuffer();
  tiles.push({input:png,left:24+(i%3)*384,top:60+Math.floor(i/3)*555});
 }
 const labels=`<svg width="1176" height="1194" xmlns="http://www.w3.org/2000/svg">${t(24,36,'JQE / APPROVED BRAND COLLECTION',20,'#17352e',700,'letter-spacing="2"')}${designs.map((d,i)=>t(24+(i%3)*384,592+Math.floor(i/3)*555,d.label,14,'#17352e',700)).join('')}</svg>`;
 tiles.push({input:Buffer.from(labels),left:0,top:0});
 await sharp({create:{width:1176,height:1194,channels:3,background:'#e8eae2'}}).composite(tiles).png().toFile(path.join(out,'collection-preview.png'));
 fs.writeFileSync(path.join(out,'QR-VALIDATION.txt'),`All 24 embedded codes decoded from final rendered flyers.\n${results.join('\n')}\nEncoded destinations: ${urls.website}, ${urls.telegram}\nEncoding validated; destination availability is not checked by this test.\n`);
 console.log('Created 6 directions × 2 sizes. All 24 QR codes decoded correctly.');
}
main().catch(e=>{console.error(e);process.exit(1)});


