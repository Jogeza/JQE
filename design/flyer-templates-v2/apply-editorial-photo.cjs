const fs=require('fs');
const sharp=require('C:/Users/moses/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const jsQR=require('jsqr');
const out=__dirname;
const H=1527.428571;
const source=fs.readFileSync('D:/Jogeza/JQE-flyer-templates/01-editorial-a4.svg','utf8');
const brand=source.slice(source.indexOf('<g id="01_Brand_Logos"'),source.indexOf('<g id="02_Headline"'));
const footer=source.slice(source.indexOf('<g id="05_CTA_and_Contact"'),source.lastIndexOf('</svg>'));
const image=fs.readFileSync('D:/Jogeza/JQE-flyer-templates/01-editorial-jqe-syntx-photo.png');
const t=(x,y,s,size,color='#f3f2eb',weight=400,attrs='')=>`<text x="${x}" y="${y}" font-family="Arial" font-size="${size}" font-weight="${weight}" fill="${color}" ${attrs}>${s}</text>`;
async function main(){
 const m=await sharp(image).metadata();
 const cropHeight=m.width*680/952;
 const body=`<rect width="1080" height="${H}" fill="#17352e"/>${brand}
 <g id="02_Editable_Headline">${t(64,180,'THE JQE WORKSPACE / SYNTX',18,'#d3e8a0',700,'letter-spacing="2"')}${t(59,269,'A clearer market',88,'#f3f2eb',700,'letter-spacing="-3"')}${t(59,356,'perspective.',88,'#d3e8a0',700,'letter-spacing="-3"')}</g>
 <g id="03_Embedded_Editorial_Photograph"><svg x="64" y="398" width="952" height="680" viewBox="0 110 ${m.width} ${cropHeight}" overflow="hidden"><image width="${m.width}" height="${m.height}" href="data:image/png;base64,${image.toString('base64')}"/></svg></g>
 <g id="04_Editable_Feature_Copy">${t(64,1132,'Read the market. Test your ideas.',32,'#f3f2eb',700)}${t(64,1178,'Keep a clear record.',32,'#f3f2eb',700)}${t(64,1230,'Research &amp; perspective for Weltrade synthetic indices.',23,'#a3b8ac')}</g>${footer}`;
 const svg=`<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="210mm" height="297mm" viewBox="0 0 1080 ${H}"><title>JQE editorial A4 — SyntX photograph</title><desc>Editable text and vector logos; embedded AI-generated illustrative photograph. Displayed interface is conceptual, not a verified product screenshot.</desc>${body}</svg>`;
 const file=out+'/01-editorial-photo-a4.svg';fs.writeFileSync(file,svg);
 await sharp(Buffer.from(svg)).resize(1080,1527).png().toFile(out+'/01-editorial-photo-a4-preview.png');
 await sharp(Buffer.from(svg)).resize(2160,3055).png().toFile(out+'/01-editorial-photo-a4-export.png');
 const raw=await sharp(Buffer.from(svg)).resize(1080,1527).ensureAlpha().raw().toBuffer({resolveWithObject:true});
 for(const [x,url] of [[724,'https://jqe.jokiholdings.com'],[884,'https://t.me/jqetrading']]){
  const b=await sharp(raw.data,{raw:raw.info}).extract({left:x,top:1304,width:136,height:136}).resize(544,544,{kernel:'nearest'}).raw().toBuffer();
  if(jsQR(new Uint8ClampedArray(b),544,544)?.data!==url)throw new Error('QR decoding failed');
 }
 console.log('Created photo A4 flyer with embedded image, editable text, both logos and two verified QR codes.');
}
main().catch(e=>{console.error(e);process.exit(1)});
