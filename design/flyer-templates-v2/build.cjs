const fs = require('fs');
const path = require('path');
const sharp = require('C:/Users/moses/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const qrcode = require('qrcode-generator');
const jsQR = require('jsqr');
const out = __dirname;
const logo = fs.readFileSync(path.join(out, 'weltrade-logo-original.svg'), 'utf8');
const logoInner = logo.slice(logo.indexOf('>')+1, logo.lastIndexOf('</svg>'));
const C = {ink:'#17352e', paper:'#f3f2eb', clay:'#b65337', lime:'#d3e8a0', muted:'#697c73', white:'#ffffff'};
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
const t = (x,y,s,size=24,color=C.ink,weight=400,extra='') => `<text x="${x}" y="${y}" font-family="Arial" font-size="${size}" font-weight="${weight}" fill="${color}" ${extra}>${esc(s)}</text>`;
const r = (x,y,w,h,c) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>`;
const line = (x,y,x2,y2,c,w=1) => `<path d="M${x} ${y}L${x2} ${y2}" fill="none" stroke="${c}" stroke-width="${w}"/>`;
const group = (name,s) => `<g id="${name}" inkscape:groupmode="layer" inkscape:label="${name}">${s}</g>`;
const destinations={website:'https://jqe.jokiholdings.com',telegram:'https://t.me/jqetrading'};
function qr(url,x,y,size){
 const q=qrcode(0,'M');q.addData(url);q.make();const n=q.getModuleCount(), unit=size/(n+8);
 let p='';for(let row=0;row<n;row++)for(let col=0;col<n;col++)if(q.isDark(row,col))p+=`M${col+4} ${row+4}h1v1h-1z`;
 return `<g transform="translate(${x} ${y}) scale(${unit})">${r(0,0,n+8,n+8,'#fff')}<path d="${p}" fill="#111"/></g>`;
}
function brand(dark=false){
  const fg=dark?C.paper:C.ink;
  return group('01_Brand_Logos', `<g id="JQE_site_lockup"><path d="M64 88h12l8-18 12 36 8-18h12" fill="none" stroke="${fg}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${t(127,105,'JQE',48,fg,800,'letter-spacing="-3"')}${t(226,103,'Quant',24,dark?C.lime:C.clay,700)}</g>${line(327,64,327,112,dark?'#547066':'#b7c3b8')}${r(354,60,225,58,C.ink)}<svg x="368" y="69" width="198" height="41" viewBox="0 0 170 35">${logoInner}</svg>`);
}
function footer(H,dark=false){
 const fg=dark?C.paper:C.ink, mu=dark?'#a3b8ac':C.muted;
 return group('05_CTA_and_Contact', `${line(64,H-250,1016,H-250,dark?'#52685c':'#c6cec3')}${t(64,H-200,'Start with perspective.',36,fg,700)}${t(64,H-151,'jqe.jokiholdings.com',27,fg,700)}${t(64,H-110,'Telegram  /  @jqetrading',25,fg)}${t(64,H-75,'Visit the website. Join the conversation.',18,mu)}`)+group('06_Scannable_QR_Codes',`${qr(destinations.website,724,H-223,136)}${qr(destinations.telegram,884,H-223,136)}${t(792,H-62,'WEBSITE',14,fg,700,'text-anchor="middle" letter-spacing="1"')}${t(952,H-62,'TELEGRAM',14,fg,700,'text-anchor="middle" letter-spacing="1"')}`)+group('07_Product_Footer',t(64,H-28,'Demo research platform. Trading involves risk. No guaranteed returns.',16,mu));
}
function svg(body,H,a4,title){return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="${a4?'210mm':'1080'}" height="${a4?'297mm':H}" viewBox="0 0 1080 ${H}"><title>${title}</title><desc>Editable JQE campaign artwork. Text remains live; logos and artwork are vectors. Abstract graphics are decorative and do not represent trading results.</desc>${body}</svg>`;}
function editorial(H){
 const d=H-1350;
 let art='';
 // Oversized Q: a graphic brand motif, not a fabricated financial chart.
 art+=`<circle cx="794" cy="827" r="190" fill="none" stroke="#496151" stroke-width="80"/>`;
 art+=`<path d="M866 907L1008 1049" stroke="${C.lime}" stroke-width="80"/>`;
 art+=line(64,631,1016,631,'#52685c');
 art+=t(64,672,'01 / RESEARCH & PERSPECTIVE',18,C.lime,700,'letter-spacing="2"');
 art+=t(64,772,'Read the market.',33,C.paper,700);
 art+=t(64,818,'Test your ideas.',33,C.paper,700);
 art+=t(64,864,'Keep a clear record.',33,C.paper,700);
 art+=t(64,945,'Built for Weltrade',23,'#a3b8ac');
 art+=t(64,980,'synthetic indices.',23,'#a3b8ac');
 if(d)art+=t(64,1060,'A workspace for a more considered process.',23,'#a3b8ac');
 return group('00_Background',r(0,0,1080,H,C.ink))+brand(true)+group('02_Headline',t(64,216,'THE JQE WORKSPACE',18,C.lime,700,'letter-spacing="3"')+t(57,340,'A clearer',116,C.paper,700,'letter-spacing="-5"')+t(57,460,'market',116,C.paper,700,'letter-spacing="-5"')+t(57,580,'perspective.',116,C.lime,700,'letter-spacing="-5"'))+group('03_Vector_Artwork_and_Features',art)+footer(H,true);
}
function research(H){
 const d=H-1350;
 let art=r(64,545,952,225+d*.5,'#e0e6d9');
 art+=`<circle cx="846" cy="656" r="78" stroke="${C.ink}" stroke-width="2" fill="none"/><circle cx="846" cy="656" r="48" stroke="${C.clay}" stroke-width="2" fill="none"/>${line(742,656,950,656,C.ink)}${line(846,552,846,760,C.ink)}<circle cx="846" cy="656" r="7" fill="${C.clay}"/>`;
 art+=t(92,592,'A MORE CONSIDERED PROCESS',17,C.muted,700,'letter-spacing="2"')+t(92,656,'Observe. Test.',43,C.ink,700)+t(92,711,'Review. Repeat.',43,C.ink,700);
 const start=825+d*.5;
 ['Market analysis','Historical research','Decision journal'].forEach((s,i)=>{let y=start+i*88;art+=line(64,y+26,1016,y+26,'#c6cec3')+t(64,y,`0${i+1}`,21,C.clay)+t(143,y,s,29,C.ink,700)+t(700,y,['Study price and context','Explore ideas with evidence','Document your decisions'][i],18,C.muted);});
 return group('00_Background',r(0,0,1080,H,C.paper))+brand()+group('02_Headline',t(64,210,'SYNTHETIC MARKETS / WELTRADE',18,C.clay,700,'letter-spacing="2"')+t(59,316,'Put research',98,C.ink,700,'letter-spacing="-4"')+t(59,418,'at the centre.',98,C.ink,700,'letter-spacing="-4"')+t(64,485,'Meet JQE. Your workspace for analysis and perspective.',26,C.muted))+group('03_Vector_Artwork_and_Features',art)+footer(H);
}
function campaign(H){
 const d=H-1350;
 let art=r(64,616,952,378+d*.65,C.ink);
 // Three distinct editorial panels; no invented performance or trade signals.
 const labels=['OBSERVE','QUESTION','REVIEW'];
 for(let i=0;i<3;i++){
 const x=90+i*306, top=651;
 art+=t(x,top,`0${i+1}`,18,'#a3b8ac')+t(x,top+302+d*.5,labels[i],21,C.paper,700,'letter-spacing="2"');
 if(i<2)art+=line(x+279,644,x+279,967+d*.6,'#53665b');
 if(i===0)art+=`<circle cx="${x+124}" cy="770" r="68" fill="none" stroke="${C.lime}" stroke-width="3"/><path d="M${x+47} 846L${x+201} 692M${x+47} 692L${x+201} 846" stroke="${C.lime}" stroke-width="2"/>`;
 if(i===1)art+=`<path d="M${x+54} 845L${x+54} 718L${x+179} 718M${x+89} 880L${x+89} 753L${x+214} 753" fill="none" stroke="${C.lime}" stroke-width="3"/>`;
 if(i===2)art+=`<circle cx="${x+128}" cy="782" r="67" fill="none" stroke="${C.lime}" stroke-width="3"/><path d="M${x+94} 782L${x+118} 806L${x+165} 758" fill="none" stroke="${C.lime}" stroke-width="4"/>`;
 }
 return group('00_Background',r(0,0,1080,H,'#d3e8a0'))+brand()+group('02_Headline',t(64,210,'INTRODUCING JQE',18,C.ink,700,'letter-spacing="3"')+t(58,339,'Less noise.',112,C.ink,700,'letter-spacing="-5"')+t(58,461,'More',112,C.ink,700,'letter-spacing="-5"')+t(58,583,'perspective.',112,C.ink,700,'letter-spacing="-5"'))+group('03_Vector_Artwork',art)+group('04_Feature_Copy',t(64,1044+d*.65,'Analysis, research and journaling for Weltrade synthetic markets.',25,C.ink))+footer(H);
}
function photo(H){
 const d=H-1350,ph=474+d*.5;
 let artwork=r(64,188,952,ph,'#dce3d7');
 artwork+=line(64,188,1016,188,'#b6c5b5')+line(64,188+ph,1016,188+ph,'#b6c5b5');
 artwork+=`<path d="M64 ${188+ph}L460 188h200L264 ${188+ph}z" fill="#c7d5c2"/>`;
 artwork+=`<circle cx="820" cy="${188+ph*.5}" r="108" fill="none" stroke="#9eb69c" stroke-width="2"/>`;
 artwork+=t(98,249,'PHOTO PLACEMENT / 952 × '+Math.round(ph)+' PX',17,C.ink,700,'letter-spacing="2"');
 artwork+=t(98,188+ph-87,'Your workspace. Your perspective.',35,C.ink,700)+t(98,188+ph-46,'Replace this panel with a real JQE workstation photograph.',21,C.muted);
 return group('00_Background',r(0,0,1080,H,C.paper))+brand()+group('03_Replaceable_Photo_Panel',artwork)+group('02_Headline',t(64,747+d*.5,'Make room for',73,C.ink,700,'letter-spacing="-2"')+t(64,827+d*.5,'a clearer view.',73,C.ink,700,'letter-spacing="-2"')+t(64,891+d*.5,'JQE / Research & perspective for Weltrade synthetic indices.',25,C.muted))+group('04_Feature_Copy',`${line(64,942+d*.5,1016,942+d*.5,'#c6cec3')}${t(64,993+d*.5,'ANALYSE',20,C.clay,700,'letter-spacing="2"')}${t(398,993+d*.5,'RESEARCH',20,C.clay,700,'letter-spacing="2"')}${t(764,993+d*.5,'REVIEW',20,C.clay,700,'letter-spacing="2"')}`)+footer(H);
}
async function main(){
 const concepts=[['01-editorial',editorial],['02-research',research],['03-campaign',campaign],['04-photo-led',photo]];
 for(const [name,fn] of concepts){
  for(const a4 of [false,true]){
   const H=a4?1527.428571:1350, suffix=a4?'a4':'social';
   const source=svg(fn(H),H,a4,name);
   fs.writeFileSync(path.join(out,`${name}-${suffix}.svg`),source);
   if(!a4) await sharp(Buffer.from(source)).png().toFile(path.join(out,`${name}-preview.png`));
   else await sharp(Buffer.from(source)).resize(540).png().toFile(path.join(out,`${name}-a4-preview.png`));
  }
 }
 const tiles=await Promise.all(concepts.map(async([name],i)=>({input:await sharp(path.join(out,`${name}-preview.png`)).resize(432,540).toBuffer(),left:32+(i%2)*464,top:32+Math.floor(i/2)*572})));
 await sharp({create:{width:960,height:1176,channels:3,background:'#e9e9e4'}}).composite(tiles).png().toFile(path.join(out,'collection-preview.png'));
 for(const [name,url] of Object.entries(destinations)){
  const standalone=svg(qr(url,0,0,1080),1080,false,`${name} QR code`);
  fs.writeFileSync(path.join(out,`qr-${name}.svg`),standalone);
  await sharp(Buffer.from(standalone)).resize(720,720).png().toFile(path.join(out,`qr-${name}.png`));
 }
 const results=[];
 for(const [name] of concepts){for(const a4 of [false,true]){
  const H=a4?1527.428571:1350;
  const svgSource=fs.readFileSync(path.join(out,`${name}-${a4?'a4':'social'}.svg`));
  const raw=await sharp(svgSource).resize(1080,Math.round(H)).ensureAlpha().raw().toBuffer({resolveWithObject:true});
  for(const [kind,x] of [['website',724],['telegram',884]]){
   const crop=await sharp(raw.data,{raw:raw.info}).extract({left:x,top:Math.round(H-223),width:136,height:136}).resize(544,544,{kernel:'nearest'}).raw().toBuffer();
   const decoded=jsQR(new Uint8ClampedArray(crop),544,544);
   if(decoded?.data!==destinations[kind])throw Error(`QR validation failed: ${name} ${a4} ${kind}`);
   results.push(`${name}-${a4?'a4':'social'}: ${kind} → ${decoded.data}`);
  }
 }}
 fs.writeFileSync(path.join(out,'QR-VALIDATION.txt'),`All 16 QR codes decoded from rendered flyer artwork.\n${results.join('\n')}\nDestination reachability was not verified; decoding verifies the encoded URLs.\n`);
 console.log('Created eight editable SVG templates. All 16 embedded QR codes decoded correctly.');
}
main().catch(e=>{console.error(e);process.exit(1)});
