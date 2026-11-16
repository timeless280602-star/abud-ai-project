const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const {url} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium', args:['--no-sandbox']});
  try {
    const page = await browser.newPage({ignoreHTTPSErrors:true});
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const choiceText = 'Choose your action in this story:\nA) Open the door\nB) Investigate the noise\nC) <img src=x onerror=alert(1)>';
    const initial = () => [{id:1,role:'user',content:'Tell a story'}, {id:2,role:'assistant',content:choiceText}];
    let messages = initial(), posts = [], fail = false, partial = false, historyFailure = false, hold;
    await page.route('**/auth/me', r => r.fulfill({json:{identity_id:'test',profile_completed:true,dashboard_access:false,permissions:[]}}));
    await page.route('**/health', r => r.fulfill({json:{status:'healthy'}}));
    await page.route('**/web/chat/projects', r => r.fulfill({json:[{id:'p1',name:'Private project',memory_mode:'project_only'}]}));
    await page.route('**/web/chat/conversations**', async r => {
      const req = r.request(), path = new URL(req.url()).pathname;
      if (path.endsWith('/messages')) {
        const body = req.postDataJSON(); posts.push(body);
        if (fail) return r.fulfill({status:503,json:{detail:'Rejected. Please retry.'}});
        if (hold) await hold;
        if (partial) {
          messages.push({id:3,role:'user',content:body.message});
          return r.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'delta',text:choiceText})+'\n\n'});
        }
        if (body.regenerate) messages = initial().map(m => m.role === 'assistant' ? {...m,id:20} : m);
        else messages.push({id:3,role:'user',content:body.message},{id:4,role:'assistant',content:'The door opens.'});
        return r.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'delta',text:messages.at(-1).content})+'\n\ndata: {"type":"done"}\n\n'});
      }
      if (path.endsWith('/conversations')) return r.fulfill({json:[{id:'abc',title:'Story'},{id:'other',title:'Other story'}]});
      if (historyFailure) return r.fulfill({status:503,json:{detail:'History unavailable. Reopen chat to retry.'}});
      return r.fulfill({json:{id:path.split('/').at(-1),messages}});
    });
    const open = async (name='Story') => {
      await page.getByRole('button',{name,exact:true}).click();
      await page.getByRole('region',{name:'Pilihan respons'}).waitFor();
    };
    const region = page.getByRole('region',{name:'Pilihan respons'});
    const confirm = region.getByRole('button',{name:'Lanjutkan dengan pilihan'});
    const a = region.getByRole('button',{name:'A. Open the door',exact:true});
    const b = region.getByRole('button',{name:'B. Investigate the noise',exact:true});
    const c = region.getByRole('button',{name:'C. <img src=x onerror=alert(1)>',exact:true});
    const idle = () => page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b=>b.textContent==='Regenerate response').disabled);
    await page.goto(url); await open();
    assert.equal(await confirm.isDisabled(),true);
    assert.equal(await region.locator('img').count(),0);
    await a.focus(); await page.keyboard.press('Space');
    assert.equal(await a.getAttribute('aria-pressed'),'true');
    await a.press('Enter'); assert.equal(await a.getAttribute('aria-pressed'),'false');
    await b.click(); await a.click(); assert.equal(await c.isDisabled(),true);
    await b.click(); assert.equal(await c.isDisabled(),false); await a.click(); await b.click(); await a.click();
    for (const width of [320,390,768,1280]) {
      await page.setViewportSize({width,height:844});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    }
    // One event turn: choice double-click plus composer submit must share a synchronous lock.
    let release; hold = new Promise(resolve => {release=resolve;});
    await page.getByLabel('Message Abud',{exact:true}).fill('Composer racing');
    await confirm.evaluate(button => {button.click();button.click();document.querySelector('.chat-composer').requestSubmit();});
    await page.waitForFunction(()=>document.querySelector('.chat-composer textarea').disabled);
    assert.equal(await confirm.isDisabled(),true);
    release(); hold=null; await idle();
    assert.equal(posts.length,1);
    assert.ok(posts[0].message.indexOf('opsi B')<posts[0].message.indexOf('opsi A'));
    assert.equal(await region.count(),0);
    await page.reload();
    await page.getByRole('button',{name:'Story',exact:true}).click(); await idle();
    assert.equal(await region.count(),0); // old choice turn is ordinary text after reload
    messages=initial(); await open('Other story'); await a.click();
    await open(); assert.equal(await confirm.isDisabled(),true); // conversation isolation
    await a.click();
    await page.getByRole('button',{name:/Private project/}).click();
    await open(); assert.equal(await confirm.isDisabled(),true); // project isolation
    await a.click();
    await page.getByRole('button',{name:'Regenerate response',exact:true}).click(); await idle();
    assert.equal(await confirm.isDisabled(),true);
    await a.click(); fail=true; await confirm.click(); await idle();
    await page.getByRole('alert').filter({hasText:'Rejected'}).waitFor();
    assert.equal(await a.getAttribute('aria-pressed'),'true'); // safe rejected-request retry
    historyFailure=true; await confirm.click(); await idle();
    assert.equal(await confirm.isDisabled(),true); // uncertain history cannot repeat a send
    historyFailure=false; fail=false; await open(); await a.click();
    await confirm.click(); await idle(); assert.equal(await region.count(),0);
    messages=initial(); await open(); await a.click(); partial=true; await confirm.click(); await idle();
    assert.equal(await region.count(),0); // failed/partial answer never enables choices
    assert.equal(await page.getByRole('button',{name:'Send',exact:true}).isDisabled(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: choices, keyboard, safe text, mobile, order, limit/deselection, synchronous send race, reload, conversation/project isolation, regenerate, retry, failed stream.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1);});
