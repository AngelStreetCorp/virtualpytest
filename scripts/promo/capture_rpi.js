const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs=require('fs');const TOKEN=fs.readFileSync(__dirname+'/.token','utf8').trim();
const VIEW={width:1920,height:1080};
const url=(p)=>`http://localhost:5073${p}${p.includes('?')?'&':'?'}auto_signed=${TOKEN}`;
const CURSOR=fs.readFileSync(__dirname+'/capture.js','utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
const KEEP=['appletv - vpt-pi3','mi - vpt-pi1','S21x - vpt-pi1','stb3 - vpt-pi1','stb4 - vpt-pi1'];
async function glide(page, x, y, pause=500){ await page.mouse.move(x,y,{steps:28}); await page.waitForTimeout(pause); await page.mouse.click(x,y); }
(async()=>{
 const b=await chromium.launch();
 // ---- stills
 { const c=await b.newContext({viewport:VIEW,ignoreHTTPSErrors:true}); const p=await c.newPage();
   await p.goto(url('/'),{waitUntil:'load',timeout:60000}); await p.waitForTimeout(3000);
   await p.goto(url('/'),{waitUntil:'load',timeout:60000}); await p.waitForTimeout(7000); await p.screenshot({path:'raw/dashboard.png'}); console.log('dashboard ok');
   await p.goto(url('/device-control'),{waitUntil:'load',timeout:60000}); await p.waitForTimeout(9000);
   // filter to the working devices via the Targets select
   const sel=p.locator('.MuiSelect-select').filter({hasText:'All Targets'}).first();
   if(await sel.count()){ await sel.click(); await p.waitForTimeout(800);
     const opts=p.locator('[role="option"], li.MuiMenuItem-root'); const n=await opts.count(); const names=[];
     for(let i=0;i<n;i++){ names.push((await opts.nth(i).innerText()).trim()); }
     console.log('target options:', names.join(' | '));
     for(let i=0;i<n;i++){ const t=names[i]; if(KEEP.some(k=>t.startsWith(k.split(' - ')[0]) && t.includes(k.split(' - ')[1]))){ await opts.nth(i).click(); await p.waitForTimeout(250);} }
     await p.keyboard.press('Escape'); await p.waitForTimeout(3000);
   } else console.log('targets select not found');
   await p.screenshot({path:'raw/devices.png'}); console.log('devices ok');
   await p.goto(url('/monitoring/heatmap'),{waitUntil:'load',timeout:60000}); await p.waitForTimeout(9000);
   const hsel=p.locator('.MuiSelect-select').filter({hasText:/^ALL$/}).first();
   if(await hsel.count()){ await hsel.click(); await p.waitForTimeout(600); const ok=p.locator('[role="option"]').filter({hasText:/^OK$/}).first(); if(await ok.count()){ await ok.click(); console.log('heatmap OK filter'); } else { console.log('options:', await p.locator('[role="option"]').allInnerTexts()); await p.keyboard.press('Escape'); } await p.waitForTimeout(6000); }
   await p.screenshot({path:'raw/heatmap.png'}); console.log('heatmap ok');
   await c.close(); }
 // ---- devices clip on stb3
 { const c=await b.newContext({viewport:VIEW,ignoreHTTPSErrors:true,recordVideo:{dir:'raw/video-devices',size:VIEW}});
   await c.addInitScript(CURSOR); const p=await c.newPage(); const marks=[]; const t0=Date.now(); const mark=l=>marks.push({label:l,t:(Date.now()-t0)/1000});
   await p.goto(url('/'),{waitUntil:'load',timeout:60000}); await p.waitForTimeout(2500);
   await p.goto(url('/device-control'),{waitUntil:'load',timeout:60000}); await p.mouse.move(960,700); await p.waitForTimeout(9000); mark('loaded');
   const title=p.locator('text=/^stb3 - vpt-pi1$/').first(); await title.waitFor({timeout:20000}); const tb=await title.boundingBox();
   await glide(p, tb.x+120, tb.y+tb.height+80, 700); mark('modal'); await p.waitForTimeout(5000);
   const take=p.getByRole('button',{name:/take control/i}).first(); if(await take.count()){ const bb=await take.boundingBox(); await glide(p,bb.x+bb.width/2,bb.y+bb.height/2); mark('take-control'); await p.waitForTimeout(3500); }
   const remote=p.getByRole('button',{name:/show remote/i}).first(); if(await remote.count()){ const bb=await remote.boundingBox(); await glide(p,bb.x+bb.width/2,bb.y+bb.height/2); mark('show-remote'); await p.waitForTimeout(4000); }
   await p.mouse.move(1500,900,{steps:30}); await p.waitForTimeout(2500); mark('end');
   await p.screenshot({path:'raw/devices-modal.png'});
   const rel=p.getByRole('button',{name:/release/i}).first(); if(await rel.count()){ await rel.click().catch(()=>{}); await p.waitForTimeout(800); }
   const vid=p.video(); await c.close(); fs.copyFileSync(await vid.path(),'raw/devices.webm'); fs.writeFileSync('raw/devices.marks.json',JSON.stringify(marks,null,1));
   console.log('devices clip', marks.map(m=>`${m.label}@${m.t.toFixed(1)}`).join(' ')); }
 await b.close();
})();
