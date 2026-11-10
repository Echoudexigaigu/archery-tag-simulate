const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {createCanvas,GlobalFonts}=require('@napi-rs/canvas');
if(fs.existsSync('C:/Windows/Fonts/msyh.ttc'))GlobalFonts.registerFromPath('C:/Windows/Fonts/msyh.ttc','Microsoft YaHei');
if(fs.existsSync('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))GlobalFonts.registerFromPath('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','Microsoft YaHei');
const html=fs.readFileSync(process.argv[2],'utf8'),out=process.argv[3];fs.mkdirSync(out,{recursive:true});
class Element {constructor(){this.children=[];this.value='';this.textContent='';this.max=240;this.replacements=0;}appendChild(e){this.children.push(e)}replaceChildren(){this.children=[];this.replacements++}}
const nodes=new Map();
for(let name of ['#field','#rack-red','#rack-blue','#rack-revive'])nodes.set(name,createCanvas(name==='#field'?1400:160,name==='#field'?970:160));
let animation;
const payload=html.match(/<script type="application\/json" id="replay-data">([\s\S]*?)<\/script>/)[1];
const context=vm.createContext({document:{getElementById(id){assert.equal(id,'replay-data');return {textContent:payload}},querySelector(s){if(!nodes.has(s))nodes.set(s,new Element());return nodes.get(s)},createElement(type){return type==='canvas'?createCanvas(1400,970):new Element()}},requestAnimationFrame:f=>{animation=f}});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context,{timeout:20000});
vm.runInContext("const originalCaption=text;text=function(s,...args){if(s===undefined||s===null)throw new Error('Undefined field caption');return originalCaption(s,...args)}",context);
for(const face of [1,-1]){
 vm.runInContext(`ctx.clearRect(0,0,1400,970);person([200,150],'#123456',false,true,false,${face})`,context);
 const g=nodes.get('#field').getContext('2d');
 const alpha=(x)=>{const a=g.getImageData(x,120,10,40).data;let n=0;for(let i=3;i<a.length;i+=4)n+=a[i];return n};
 if(face===1)assert(alpha(210)>alpha(180),'Red bow must face right');
 else assert(alpha(180)>alpha(210),'Blue bow must face left');
}
// The duck silhouette must visibly lower; changing only a caption is not enough.
const upperInk=()=>{const a=nodes.get('#field').getContext('2d').getImageData(188,120,28,15).data;let n=0;for(let i=3;i<a.length;i+=4)n+=a[i];return n};
vm.runInContext("ctx.clearRect(0,0,1400,970);person([200,150],'#123456',false,true,false,1,null)",context);
const uprightInk=upperInk();
vm.runInContext("ctx.clearRect(0,0,1400,970);person([200,150],'#123456',true,true,false,1,'duck')",context);
assert(uprightInk>upperInk()+1000,'Duck must visibly lower the body');
for(const bearing of [0,Math.PI,Math.PI/2]){
 vm.runInContext(`ctx.clearRect(0,0,1400,970);person([200,150],'#123456',false,true,false,1,null,[0,0],${bearing})`,context);
 const g=nodes.get('#field').getContext('2d'),ink=(x,y,w,h)=>{const a=g.getImageData(x,y,w,h).data;let n=0;for(let i=3;i<a.length;i+=4)n+=a[i];return n};
 if(bearing===0)assert(ink(211,125,12,28)>ink(177,125,12,28),'Actual right aim points right');
 else if(bearing===Math.PI)assert(ink(177,125,12,28)>ink(211,125,12,28),'Actual left aim points left');
 else assert(ink(196,116,8,8)>0,'Actual upward aim points upward');
}
for(let caseIndex=0;caseIndex<vm.runInContext('data.cases.length',context);caseIndex++){
 vm.runInContext(`selectMatch(${caseIndex})`,context);
 vm.runInContext(`for(let i=data.cases[match].frames.length-1;i>=0;i-=17){const f=decodeFrame(i);if(f.arrows.length+f.players.reduce((n,p)=>n+p.ammo,0)!==36)throw new Error('Seeking changed arrow conservation at frame '+i)}`,context);
 const events=nodes.get('#events').children;
 const hit=vm.runInContext("data.cases[match].events.find(e=>e.kind==='queue_join')?.t",context);
 const dodge=vm.runInContext("data.cases[match].events.find(e=>e.kind==='evade_move')?.t",context);
 const duck=vm.runInContext("data.cases[match].events.find(e=>e.kind==='evade_move'&&e.style==='duck')?.t",context);
 for(let t of [0,5,20,55,...(hit===undefined?[]:[hit+.4]),...(dodge===undefined?[]:[dodge+.1]),...(duck===undefined?[]:[duck+.1]),vm.runInContext('data.cases[match].summary.duration_s',context)]){
  nodes.get('#seek').value=t;nodes.get('#seek').oninput({target:{value:t}});
  fs.writeFileSync(path.join(out,`field_case_${caseIndex}_t_${t}.png`),nodes.get('#field').toBuffer('image/png'));
 }
 if(events.length){events[0].onclick();assert.equal(vm.runInContext('playing',context),false)}
}
vm.runInContext('selectMatch(0)',context);nodes.get('#play').onclick();assert.equal(vm.runInContext('playing',context),true);
animation(0);animation(50);assert(vm.runInContext('time',context)>0);
nodes.get('#speed').onchange({target:{value:'4'}});assert.equal(vm.runInContext('speed',context),4);
nodes.get('#restart').onclick();assert.equal(vm.runInContext('time',context),0);
const sample=vm.runInContext(`(()=>{const a=decodeFrame(0),b=decodeFrame(1);const i=a.players.findIndex((p,i)=>p.position.some((v,k)=>v!==b.players[i].position[k]));time=(a.t+b.t)/2;const p=frame().players[i];return {actual:p.position,expected:a.players[i].position.map((v,k)=>(v+b.players[i].position[k])/2),from:a.players[i].position,to:b.players[i].position}})()`,context);
assert(sample.actual.every((v,i)=>Math.abs(v-sample.expected[i])<1e-7));assert.notDeepEqual(sample.actual,sample.from);assert.notDeepEqual(sample.actual,sample.to);
const before=nodes.get('#red-queue').replacements;
vm.runInContext('time=0;draw();time=.001;draw();time=.002;draw()',context);
assert(nodes.get('#red-queue').replacements<=before+1,'Unchanged queue must not be rebuilt every draw');
nodes.get('#intent-toggle').onchange({target:{checked:false}});assert.equal(vm.runInContext('showIntents',context),false);
nodes.get('#height-toggle').onchange({target:{checked:true}});assert.equal(vm.runInContext('showHeights',context),true);
nodes.get('#intent-toggle').onchange({target:{checked:true}});nodes.get('#height-toggle').onchange({target:{checked:false}});
nodes.get('#mind-toggle').onchange({target:{checked:true}});assert.equal(vm.runInContext('showMind',context),true);
assert.equal(nodes.get('#profiles').children.length,12,'All selected demo profiles must be visible');
vm.runInContext('time=20;draw()',context);fs.writeFileSync(path.join(out,'attention_overlay.png'),nodes.get('#field').toBuffer('image/png'));
nodes.get('#mind-toggle').onchange({target:{checked:false}});
const begin=performance.now();vm.runInContext('for(let i=0;i<180;i++){time=20+i/60;draw()}',context,{timeout:20000});const elapsed=performance.now()-begin;
fs.writeFileSync(path.join(out,'render_checks.json'),JSON.stringify({cases:vm.runInContext('data.cases.length',context),team_facing_verified:true,bow_direction_verified:true,interpolation_verified:true,queue_cache_verified:true,toggles_verified:true,attention_overlay_verified:true,selected_profiles_verified:true,duck_silhouette_verified:true,canvas_mean_draw_ms:elapsed/180},null,2));
for(let id of ['#rack-red','#rack-revive','#rack-blue'])fs.writeFileSync(path.join(out,id.slice(1)+'.png'),nodes.get(id).toBuffer('image/png'));
console.log('Replay drawing, controls, interpolation and caching passed for '+vm.runInContext('data.cases.length',context)+' cases; mean Canvas draw '+(elapsed/180).toFixed(2)+' ms.');
