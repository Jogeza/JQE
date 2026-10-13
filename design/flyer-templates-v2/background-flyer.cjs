const fs=require('fs');
const sharp=require('C:/Users/moses/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const jsQR=require('jsqr');
const H=1527.428571,out=__dirname;
const original=fs.readFileSync('D:/Jogeza/JQE-flyer-templates/01-editorial-a4.svg','utf8');
const brand=original.slice(original.indexOf('<g id="01_Brand_Logos"'),original.indexOf('<g id="02_Headline"'));
const qr=original.slice(original.indexOf('<g id="06_Scannable_QR_Codes"'),original.indexOf('<g id="07_Product_Footer"'));
const photo=fs.readFileSync('D:/Jogeza/JQE-flyer-templates/01-editorial-jqe-syntx-photo.png').toString('base64');
const t=(x,y,s,size,color='#f6f4ea',weight=400,attrs='')=>`<text x="${x}" y="${y}" font-family="Arial" font-size="${size}" font-weight="${weight}" fill="${color}" ${attrs}>${s}</text>`;
const svg=`<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="210mm" height="297mm" viewBox="0 0 1080 ${H}"><title>JQE — full background editorial campaign</title><desc>Live editable typography, vector logos and QR codes, embedded illustrative AI photo. A4 RGB, no bleed.</desc>
<defs><linearGradient id="top" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#081d17" stop-opacity=".94"/><stop offset=".30" stop-color="#081d17" stop-opacity=".70"/><stop offset=".48" stop-color="#081d17" stop-opacity="0"/></linearGradient><linearGradient id="bottom" x1="0" y1="0" x2="0" y2="1"><stop offset=".58" stop-color="#081d17" stop-opacity="0"/><stop offset=".75" stop-color="#081d17" stop-opacity=".84"/><stop offset="1" stop-color="#081d17" stop-opacity="1"/></linearGradient></defs>
<g id="01_Full_Background_Photo"><image width="1080" height="${H}" preserveAspectRatio="xMidYMid slice" href="data:image/png;base64,${photo}"/></g>
<g id="02_Readability_Overlays"><rect width="1080" height="${H}" fill="url(#top)"/><rect width="1080" height="${H}" fill="url(#bottom)"/></g>
${brand}
<g id="03_Editable_Headline">${t(64,189,'JQE / SYNTHETIC MARKET RESEARCH',17,'#d3e8a0',700,'letter-spacing="2.5"')}${t(58,285,'Look closer.',104,'#f6f4ea',700,'letter-spacing="-4"')}${t(58,390,'See clearer.',104,'#d3e8a0',700,'letter-spacing="-4"')}</g>
<g id="04_Editable_Benefits"><path d="M64 1096h55" stroke="#d3e8a0" stroke-width="3"/>${t(64,1151,'Your market. A fresh perspective.',36,'#f6f4ea',700)}${t(64,1195,'Analysis, research and journaling for Weltrade synthetic indices.',23,'#dde5d9')}</g>
<g id="05_Editable_Contact"><path d="M64 1256h952" stroke="#a3b8ac" stroke-opacity=".35"/>${t(64,1327,'Explore JQE.',38,'#f6f4ea',700)}${t(64,1377,'jqe.jokiholdings.com',27,'#f6f4ea',700)}${t(64,1419,'Telegram / @jqetrading',24)}${t(64,1453,'Scan to explore. Stay connected.',18,'#b5c5b7')}</g>
${qr}
<g id="07_Editable_Footer">${t(64,1499,'Demo research platform. Trading involves risk. No guaranteed returns.',16,'#b5c5b7')}</g></svg>`;
async function main(){
fs.writeFileSync(out+'/05-background-editorial-a4.svg',svg);
await sharp(Buffer.from(svg)).resize(1080,1527).png().toFile(out+'/05-background-editorial-preview.png');
await sharp(Buffer.from(svg)).resize(2160,3055).png().toFile(out+'/05-background-editorial-export.png');
const raw=await sharp(Buffer.from(svg)).resize(1080,1527).ensureAlpha().raw().toBuffer({resolveWithObject:true});
for(const [x,url] of [[724,'https://jqe.jokiholdings.com'],[884,'https://t.me/jqetrading']]){const b=await sharp(raw.data,{raw:raw.info}).extract({left:x,top:1304,width:136,height:136}).resize(544,544,{kernel:'nearest'}).raw().toBuffer();if(jsQR(new Uint8ClampedArray(b),544,544)?.data!==url)throw Error('QR failed');}
console.log('Created full-background flyer; both QR codes verified.');}
main().catch(e=>{console.error(e);process.exit(1)});

