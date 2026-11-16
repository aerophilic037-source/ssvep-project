/** Pure JS lifecycle tests with a fake DOM/clock. Does NOT verify browser layout,
 * physical refresh, speech output, or fullscreen. Run: node this-file.mjs
 */
import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { Blob } from 'node:buffer';

export async function runFrontendChecks() {
  const root = new URL('./', import.meta.url);
  const report = await fs.readFile(new URL('validation_static/report.js', root), 'utf8');
  const app = await fs.readFile(new URL('validation_static/app.js', root), 'utf8');
  const html = await fs.readFile(new URL('validation_static/index.html', root), 'utf8');
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
  class Element {
    constructor() { this.value='';this.textContent='';this.checked=false;this.children=[];this.style={}; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children=children; }
    add(child) { this.append(child); }
  }
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
  const listeners={},windowListeners={},callbacks=new Map(),posts=[];
  let callbackId=0,clock=0;
  const document={hidden:false,getElementById:id=>{assert.ok(elements[id],`Missing HTML id ${id}`);return elements[id];},
    createElement:()=>new Element(),createTextNode:text=>({textContent:text}),querySelectorAll:()=>[],
    addEventListener:(event,fn)=>{listeners[event]=fn;}};
  const window={addEventListener:(event,fn)=>{windowListeners[event]=fn;}};
  const context=vm.createContext({document,window,Option:Element,AbortController,Blob,URL,
    localStorage:{getItem:()=>null,setItem:()=>{}},performance:{now:()=>clock},
    setTimeout:()=>++callbackId,clearTimeout:()=>{},setInterval:()=>0,
    requestAnimationFrame:fn=>{const id=++callbackId;callbacks.set(id,fn);return id;},
    cancelAnimationFrame:id=>callbacks.delete(id),
    fetch:async(url,options)=>{if(options?.body)posts.push({url,body:JSON.parse(options.body)});
      return {ok:true,json:async()=>url.endsWith('status')?{connected:false,receiving:false}:{} };}});
  vm.runInContext(report,context,{filename:'report.js'});
  vm.runInContext(app,context,{filename:'app.js'});
  await Promise.resolve();await Promise.resolve();
  const run=code=>vm.runInContext(code,context);
  function frame(time){clock=time;const queued=[...callbacks.values()];callbacks.clear();queued.forEach(fn=>fn(time));}

  // Completed intervals stop scheduling callbacks and return monotonically
  // ordered frame times. No autonomous flicker is scheduled at page load.
  assert.equal(callbacks.size,0);
  const complete=run('animate({condition:"single",frequency:12,duration:.1},generation)');
  frame(1000);frame(1050);frame(1100);
  const result=await complete;
  assert.equal(result.aborted,false);
  assert.deepEqual(Array.from(result.times),[0,50,100]);
  assert.equal(callbacks.size,0);
  assert.equal(elements.stimuli.children[0].textContent,'+');

  // Escape while flicker is active settles the animation promise, clears all
  // queued frames and immediately restores a neutral display.
  run('running=true');
  const interrupted=run('animate({condition:"choice",duration:10},generation)');
  frame(2000);
  assert.equal(elements.stimuli.children.length,3);
  listeners.keydown({key:'Escape'});
  assert.equal((await interrupted).aborted,true);
  assert.equal(callbacks.size,0);
  assert.equal(elements.stimuli.children[0].textContent,'+');
  assert.equal(run('running'),false);

  // Hidden tabs and page unload must neutralize a running display.
  run('running=true');
  const hidden=run('animate({condition:"single",frequency:15,duration:10},generation)');
  frame(3000);document.hidden=true;listeners.visibilitychange();
  assert.equal((await hidden).aborted,true);
  assert.equal(callbacks.size,0);
  run('running=true');document.hidden=false;
  const fullscreenExit=run('animate({condition:"single",frequency:15,duration:10},generation)');
  frame(4000);document.fullscreenElement=null;listeners.fullscreenchange();
  assert.equal((await fullscreenExit).aborted,true);
  assert.equal(callbacks.size,0);
  run('current={id:"pending"}');
  windowListeners.pagehide();
  assert.equal(posts.at(-1).url,'/api/block/finish');
  assert.equal(posts.at(-1).body.aborted,true);

  // All setup and capture controls stay disabled during a pending capture.
  run('controls()');
  assert.equal(elements.run.disabled,true);
  assert.equal(elements['save-setup'].disabled,true);
  assert.equal(elements.stop.disabled,false);
  assert.equal(elements['stage-stop'].disabled,false);
  return {checks:5,passed:true,scope:'Fake DOM/clock only; physical browser and display not tested'};
}

// The export also allows execution in a persistent Node REPL without spawning
// another browser or interacting with the user's computer UI.
if (import.meta.url === `file://${globalThis.process?.argv?.[1]}`) {
  console.log(await runFrontendChecks());
}
