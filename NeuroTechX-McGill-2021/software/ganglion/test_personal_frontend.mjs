// DOM-contract test only; does not claim real browser rendering/timing validation.
import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const root=new URL('./native_static/',import.meta.url);
const markup=await fs.readFile(new URL('index.html',root),'utf8');
class Element {
 constructor(){this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.children=[];this.style={};this.classList={add(){},toggle(){}};}
 append(...x){this.children.push(...x);} replaceChildren(...x){this.children=x;} add(x){this.children.push(x);}
 closest(){return this;} querySelector(){return new Element();} getBoundingClientRect(){return {width:150};}
}
const elements=Object.fromEntries([...markup.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
for(const [id,value]of Object.entries({protocol:'single15',streams:'native',units:'uV',lsl_filters:'off','personal-distance':'60','personal-size':'4'}))elements[id].value=value;
let experiment=null;
const context=vm.createContext({console,URL,URLSearchParams,AbortController,setTimeout,clearTimeout,performance,
 setInterval(){},requestAnimationFrame(){},cancelAnimationFrame(){},location:{search:'?mode=personal'},
 Option:class extends Element{constructor(text,value){super();this.value=value;this.textContent=text;}},
 localStorage:{getItem(){return null;},setItem(){}},window:{addEventListener(){}},
 document:{body:new Element(),getElementById(id){assert.ok(elements[id],`Unknown DOM ID ${id}`);return elements[id];},
 createElement(){return new Element();},createTextNode(t){return t;},querySelectorAll(){return [];},addEventListener(){}},
 fetch:async(path,options)=>({ok:true,json:async()=>{
  if(path==='/api/status')return {receiving:true,connected:true,stream:{name:'TEST',channels:4,sampling_rate:200}};
  if(path==='/api/personal/status')return experiment;
  if(path==='/api/session'&&options.method==='POST')return {id:'TEST_SESSION'};
  if(path==='/api/personal/prepare'){experiment={calibration_completed:0,evaluation_completed:0,model_id:null,algorithms:{}};return experiment;}
  if(path==='/api/personal/train'){experiment.model_id='FROZEN';return experiment;}
  throw Error('Unexpected fetch '+path);
 }})});
for(const name of ['report.js','app.js','personal.js'])new vm.Script(await fs.readFile(new URL(name,root),'utf8'),{filename:name}).runInContext(context);
await new Promise(r=>setTimeout(r,0));
assert.equal(elements['personal-panel'].hidden,false);
assert.equal(elements['personal-evaluate'].disabled,true);
await vm.runInContext("$('save-setup').onclick()",context);
assert.equal(elements['personal-prepare'].disabled,false);
await vm.runInContext("$('personal-prepare').onclick()",context);
assert.equal(elements['personal-calibrate'].disabled,false);
assert.equal(elements['personal-train'].disabled,true);
experiment.calibration_completed=45;
await vm.runInContext('personalRefresh();',context);
assert.equal(elements['personal-train'].disabled,false);
await vm.runInContext("$('personal-train').onclick()",context);
assert.equal(elements['personal-calibrate'].disabled,true);
assert.equal(elements['personal-train'].disabled,true);
assert.equal(elements['personal-evaluate'].disabled,false);
experiment.evaluation_completed=45;
await vm.runInContext('personalRefresh();',context);
assert.equal(elements['personal-evaluate'].disabled,true);
console.log('Personal frontend DOM contract and stage controls passed');
