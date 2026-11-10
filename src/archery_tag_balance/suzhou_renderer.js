const data=JSON.parse(document.getElementById('replay-data').textContent);
const $=s=>document.querySelector(s),canvas=$('#field'),cfg=data.config;
let ctx=canvas.getContext('2d');
const COLORS={attack:'#bd4d43',defense:'#376b9a',revive:'#a77d20'};
let match=0,time=0,playing=false,last=null,speed=1,showIntents=true,showHeights=false,showMind=false;
let previousHud='',previousClock=-1,cachedFrameIndex=0,frameWindows=0,windowStart=0;
let decodeCache=new Map(),lastDecodedIndex=-1,lastArrowTable=new Map();
const boardCache={},sx=34,ox=156,oy=150;
const background=document.createElement('canvas');background.width=1400;background.height=970;
function point(x,y){return [ox+x*sx,oy+(20-y)*sx]}
const labelCache=new Map();
function text(s,x,y,color='#4c6255',size=14,align='center'){
 const key=JSON.stringify([s,color,size]);let label=labelCache.get(key);
 if(!label){
  const font=`${size}px Arial,"Microsoft YaHei"`;ctx.font=font;
  const width=Math.ceil(ctx.measureText(s).width)+4,height=Math.ceil(size*1.8),baseline=Math.ceil(size*1.25);
  const tile=document.createElement('canvas');tile.width=width;tile.height=height;
  const g=tile.getContext('2d');g.font=font;g.fillStyle=color;g.textAlign='left';g.fillText(s,2,baseline);
  label={tile,width,baseline};labelCache.set(key,label);
  if(labelCache.size>1200)labelCache.delete(labelCache.keys().next().value);
 }
 const left=align==='center'?x-label.width/2:align==='right'?x-label.width+2:x-2;
 ctx.drawImage(label.tile,left,y-label.baseline);
}
function line(a,b,color,width=1,dash=[]){ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();ctx.setLineDash([])}
function rect(x,y,w,h,color){ctx.fillStyle=color;ctx.fillRect(x,y,w,h)}
function circle(x,y,r,color,stroke){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);if(color){ctx.fillStyle=color;ctx.fill()}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=1.6;ctx.stroke()}}
function name(id){return cfg.roster[id]?.name||id||'队友'}
function fmt(t){return `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`}
function blend(a,b,f){return a.map((v,i)=>v+(b[i]-v)*f)}
function decodeFrame(i){
 if(decodeCache.has(i))return decodeCache.get(i);
 const fs=data.cases[match].frames,f=fs[i];let table;
 if(i===lastDecodedIndex+1&&!f.k)table=new Map(lastArrowTable);
 else {let start=i;while(start>0&&!fs[start].k)start--;table=new Map();for(let j=start;j<i;j++){if(fs[j].k)table.clear();for(let id of fs[j].d)table.delete(id);for(let row of fs[j].a)table.set(row[0],row)}}
 if(f.k)table.clear();for(let id of f.d)table.delete(id);for(let row of f.a)table.set(row[0],row);
 const ids=data.ids,score={attack:{alive:f.s[0],target:f.s[1],total:f.s[0]+f.s[1]},defense:{alive:f.s[2],target:f.s[3],total:f.s[2]+f.s[3]}};
 const decoded={t:f.t,players:f.p.map((p,j)=>({id:ids[j],team:j<6?'attack':'defense',position:p.slice(0,2),status:p[2]?'eliminated':'active',ammo:p[3],crouched:!!p[4],stage:data.stages[p[5]],revive_runner:!!p[6],role:data.roles[p[13]],bow_state:['empty','nocking','ready'][p[14]],hand_arrows:p[15],out_stage:['hit','leaving','waiting','returning',null][p[16]],evasion_kind:[null,'sidestep','duck'][p[17]||0],job_partner:ids[p[18]],mind_focus:p[19],mind_pressure:p[20],mind_risk:p[21],aim_key:p[22],aim_elapsed:p[23]||0,aim_required:p[24]||1,dodge_velocity:[p[25]||0,p[26]||0],bow_bearing:p[27],aim_point:p[28]===null?null:[p[28],p[29]],team_mode:p[30]||'balanced',team_task:p[31]||'post',ammo_requested:!!p[32],transport_quota:p[33]||0,objective:p[34]||'revival_live',out_position:p[7]===null?null:[p[7],p[8]],intent:{kind:data.intents[p[9]],goal:p[10]===null?null:[p[10],p[11]],arrow:p[12]}})),arrows:[...table.values()].map(b=>({id:b[0],position:b.slice(1,4),state:['ground','flying','settling','tossed','discard_pending'][b[4]],hand_throw:!!b[8],shooter:ids[b[5]],velocity:[b[6]||0,b[7]||0,0]})),racks:Object.fromEntries(['attack','defense','revive'].map((key,j)=>[key,[0,1,2,3,4].map(k=>!!(f.r[j]&(1<<k)))])),queue:{attack:f.q[0].map(i=>ids[i]),defense:f.q[1].map(i=>ids[i])},approved:f.v.map(i=>ids[i]),score};
 lastDecodedIndex=i;lastArrowTable=table;decodeCache.set(i,decoded);if(decodeCache.size>8)decodeCache.delete(decodeCache.keys().next().value);return decoded;
}
function bracket(t){
 const fs=data.cases[match].frames;
 let i=cachedFrameIndex;
 if(t<fs[i].t||i+5<fs.length&&t>fs[i+5].t){let lo=0,hi=fs.length-1;while(lo<hi){let m=Math.ceil((lo+hi)/2);if(fs[m].t<=t)lo=m;else hi=m-1}i=lo}
 else while(i+1<fs.length&&fs[i+1].t<=t)i++;
 cachedFrameIndex=i;
 const a=decodeFrame(i),b=decodeFrame(Math.min(i+1,fs.length-1));
 return {a,b,f:b.t>a.t?Math.max(0,Math.min(1,(t-a.t)/(b.t-a.t))):0};
}
function frame(){
 const {a,b,f}=bracket(time);
 if(!f)return a;
 const people=new Map(b.players.map(p=>[p.id,p])),arrows=new Map(b.arrows.map(p=>[p.id,p]));
 return {...a,players:a.players.map(p=>{const q=people.get(p.id);if(!q||p.status!==q.status)return p;return {...p,position:blend(p.position,q.position,f),bow_bearing:p.bow_bearing+((q.bow_bearing-p.bow_bearing+Math.PI*3)%(Math.PI*2)-Math.PI)*f,out_position:p.out_position&&q.out_position?blend(p.out_position,q.out_position,f):p.out_position}}),
 arrows:a.arrows.map(p=>{const q=arrows.get(p.id);return q&&p.state!=='ground'?{...p,position:blend(p.position,q.position,f)}:p})};
}
function staticField(){
 const mainContext=ctx;ctx=background.getContext('2d');
 rect(0,0,1400,970,'#f4f2ec');
 rect(...point(0,20),32*sx,20*sx,'#d6e0ca');
 for(let x=0;x<32;x+=2)rect(...point(x,20),sx,20*sx,'#cfdbc4');
 const [nlo,nhi]=cfg.suzhou.no_shoot_x_bounds_m;
 rect(...point(nlo,20),(nhi-nlo)*sx,20*sx,'#e5dfc8');
 for(let x=0;x<=32;x+=2)line(point(x,0),point(x,20),'#5268530d');
 for(let y=0;y<=20;y+=2)line(point(0,y),point(32,y),'#5268530d');
 ctx.strokeStyle='#fdfdf8';ctx.lineWidth=3;ctx.strokeRect(...point(0,20),32*sx,20*sx);
 line(point(16,0),point(16,20),'#fdfdf8',2);
 for(let x of [nlo,nhi])line(point(x,0),point(x,20),'#9d8b50',1,[6,6]);
 text('红队半场',...point(7.5,22.2),COLORS.attack,19);text('蓝队半场',...point(24.5,22.2),COLORS.defense,19);
 text('32 m',700,oy+20*sx+72,'#73806f',14);text('20 m',70,oy+10*sx,'#73806f',14);
 text('禁射区 · 中线两侧各 5 m',700,oy-12,'#8b743c',13);
 for(let team of ['attack','defense']){
  let x=cfg.suzhou.arrow_line_x_m[team];line(point(x,0),point(x,20),'#6a7b5770',1,[4,7]);
  let [px,py]=cfg.suzhou.revive_pads[team],p=point(px,py),[w,h]=cfg.suzhou.revive_pad_size_m;
  rect(p[0]-w*sx/2,p[1]-h*sx/2,w*sx,h*sx,'#b28c32');circle(...p,15,null,'#a3843b80');
  text('复活踩点',p[0],p[1]+32,'#86671e',11);
  let [wx,wy]=cfg.suzhou.waiting_positions_m[team];line(point(wx-2.6,wy),point(wx+2.6,wy),COLORS[team]+'66',2,[6,6]);
  text(`${team==='attack'?'红':'蓝'}队复活等待区`,...point(wx,wy-.6),COLORS[team],11);
 }
 for(let o of cfg.obstacles){
  let [x,y]=o.center_xy_m,[depth,width,height]=o.size_xyz_m,p=point(x-depth/2,y+width/2);
  rect(p[0]+3,p[1]+4,depth*sx,width*sx,'#66725f33');rect(p[0],p[1],depth*sx,width*sx,'#a0aa94');
  ctx.strokeStyle='#5e6c58';ctx.lineWidth=1.8;ctx.strokeRect(p[0],p[1],depth*sx,width*sx);
  if(o.shape==='tapered_square'){let top=o.top_size_xy_m,q=point(x-top[0]/2,y+top[1]/2);rect(...q,top[0]*sx,top[1]*sx,'#c3cbbb');ctx.strokeStyle='#788770';ctx.lineWidth=1;ctx.strokeRect(...q,top[0]*sx,top[1]*sx)}
  text(`${height>1?'高':'矮'} ${height.toFixed(1)}m`,...point(x,y+width/2+.4),'#4a5d45',11);
 }
 for(let [key,r] of [...cfg.skirmish_racks.map(r=>[r.team,r]),['revive',cfg.suzhou.revive_rack]]){
  let p=point(...r.position_xyz_m);rect(p[0]-3,p[1]-.3*sx,6,.6*sx,COLORS[key]);
  text(key==='revive'?'共用复活靶':key==='attack'?'红方得分靶':'蓝方得分靶',p[0],p[1]-22,COLORS[key],11);
 }
 for(let team of ['attack','defense']){const [wx,wy]=cfg.suzhou.waiting_positions_m[team];for(let i=0;i<6;i++){let p=point(wx+(i-2.5)*cfg.v3.waiting_spacing_m,wy);ctx.strokeStyle='#a7af9c';ctx.lineWidth=1;ctx.strokeRect(p[0]-10,p[1]-10,20,20)}}
 text('身高参照',1325,235,'#6b7964',11);for(let [x,h,label,color] of [[1285,1.7,'人','#667b60'],[1320,1.5,'高','#a0aa94'],[1355,.8,'矮','#a0aa94']]){rect(x-8,315-h*35,16,h*35,color);text(label,x,333,'#6b7964',10);text(h+'m',x,350,'#6b7964',9)}
 text('身宽 0.50m',1320,375,'#6b7964',10);
 text('实线射箭可命中 · 虚线扔箭始终无伤害 · 人物足下圈为真实占地',700,943,'#8b907d',12);
 ctx=mainContext;
}
function drawBoard(id,key,f){
 const state=f.racks[key].map(Number).join('');if(boardCache[key]===state)return;boardCache[key]=state;
 const g=$(id).getContext('2d');g.clearRect(0,0,160,160);g.fillStyle='#dbddd5';g.fillRect(10,10,140,140);
 const spec=key==='revive'?cfg.suzhou.revive_rack:cfg.skirmish_racks.find(r=>r.team===key);
 for(let k=0;k<5;k++){
  let [h,v]=spec.offsets_hv_m[k],r=spec.spot_radii_m[k]*205;
  g.beginPath();g.arc(80+h*205,80-v*205,r,0,Math.PI*2);g.fillStyle=f.racks[key][k]?'#d3b16e':'#48524b';g.fill();
  g.fillStyle=f.racks[key][k]?'#4d4229':'#dbe1d8';g.font='12px Arial,"Microsoft YaHei"';g.textAlign='center';
  g.fillText(key==='revive'?String(k+1):`${spec.spot_weights[k]}分`,80+h*205,84-v*205);
 }
}
function hud(f){
 const signature=JSON.stringify([f.racks,f.queue,f.approved,f.score,f.players.map(p=>[p.role,p.status,p.team_mode])]);
 if(signature!==previousHud){
  previousHud=signature;
  for(let [team,label] of [['attack','red'],['defense','blue']]){
   const mode=f.players.find(p=>p.team===team&&p.status==='active')?.team_mode;$('#'+label+'-plan').textContent=`${team==='attack'?'红':'蓝'}队 · ${({balanced:'常规分路',lockdown:'人数优势：前压 / 架弓 / 控箭',outnumbered:'人数劣势：复活 / 退守'})[mode]||'已离场'}${f.players.find(p=>p.team===team&&p.status==='active')?.objective==='score_battle'?' · 复活耗尽，靶区攻防':''}`;
   const s=f.score[team];$('#'+label+'-score').textContent=`${team==='attack'?'红':'蓝'}队 · ${s.total} 分`;
   $('#'+label+'-detail').textContent=`在场 ${s.alive}/6 · 剩余靶点 ${f.racks[team].filter(Boolean).length}/5（${s.target} 分）`;
   drawBoard('#rack-'+label,team,f);let el=$('#'+label+'-queue');el.replaceChildren();
   for(let [i,id] of f.queue[team].entries()){let chip=document.createElement('span');chip.className='chip';chip.textContent=`${i+1}. ${name(id)}`;el.appendChild(chip)}
   for(let id of f.approved.filter(id=>id.startsWith(team))){let chip=document.createElement('span');chip.className='chip';chip.textContent=`${name(id)} · 获得资格，返回中`;el.appendChild(chip)}
   if(!el.children.length)el.textContent='无人等待';
  }
  for(let role of data.roles)for(let team of ['attack','defense']){const p=f.players.find(p=>p.team===team&&p.role===role&&p.status==='active');$('#role-'+team+'-'+role).textContent=p?name(p.id):'空缺'}
  $('#role-label-revive_lane').textContent=f.racks.revive.some(Boolean)?'复活路':'靶区支援';drawBoard('#rack-revive','revive',f);$('#revive-detail').textContent=`剩余 ${f.racks.revive.filter(Boolean).length}/5 · 每点复活 1 人`;
 }
 if(Math.floor(time*10)!==previousClock){previousClock=Math.floor(time*10);$('#clock').textContent=`${fmt(time)} / ${fmt(data.cases[match].summary.duration_s)}`;$('#seek').value=time}
 const m=data.cases[match];const reasons={target_clear:'清空得分靶',elimination:'全部出局',remaining_score:'时间结束，比较剩余分数',mutual_loss:'双方同时触发败局'};
 const result=time>=m.summary.duration_s&&m.summary.winner==='ongoing'?'测试片段结束 · 不结算胜负':time>=m.summary.duration_s?`${m.summary.winner==='draw'?'平局':m.summary.winner==='attack'?'红队获胜':'蓝队获胜'} · ${reasons[m.summary.victory_reason]||m.summary.victory_reason}`:'中央小点 2 分 · 四角大点各 1 分 · 清空对方得分靶立即获胜';
 if($('#result').textContent!==result)$('#result').textContent=result;
}
const intentLabels={gather:'集箭',cache:'布置备用箭',pickup:'取箭',search:'寻找箭',revive:'复活射手',shoot_low:'瞄下盘',shoot:'瞄准',hold:'就位',batch_collect:'批量回收',batch_deliver:'运箭',batch_stash:'布置备用箭'};
const roleShort={high_flank:'高边',high_cover:'高掩',center_1:'中一',center_2:'中二',low_cover:'矮掩',revive_lane:'复活路'};
function person(q,c,crouch,loaded,out=false,face=1,evasion=null,velocity=[0,0],bearing=null){
 ctx.save();ctx.translate(q[0],q[1]);ctx.scale(face,1);
 const duck=evasion==='duck',side=evasion==='sidestep',h=duck?10:crouch?14:25;
 circle(0,0,8.5,null,c+'45');
 if(side){
  const lateral=Math.sign(velocity[1]||1),lean=-lateral*3.5;
  ctx.globalAlpha=.20;rect(-5, -18-lateral*4,10,13,c);circle(0,-22-lateral*4,4,c);ctx.globalAlpha=1;
  line([-6,4],[-3,-5],c,2.3);line([7,-3],[2,-5],c,2.3);
  ctx.translate(lean,-2);ctx.rotate(lateral*.28);
 }else{line([-4,2],[-3,-3],c,2);line([4,2],[3,-3],c,2)}
 rect(-6,-h+9,12,Math.max(3,h-10),c);circle(0,-h+5,4.2,c);
 if(duck){line([-7,-1],[6,-1],c,3);line([2,-4],[8,-7],c,2)}
 if(out)line([6,-h+13],[11,-h],c,2);
 else if(bearing===null){ctx.beginPath();ctx.strokeStyle=c;ctx.lineWidth=1.4;ctx.arc(6,-h+13,7,-1.2,1.2);ctx.stroke();if(loaded)line([3,-h+13],[17,-h+13],c,1.5)}
 ctx.restore();
 if(!out&&bearing!==null){
  ctx.save();ctx.translate(q[0],q[1]-(duck?4:crouch?7:12));ctx.rotate(-bearing);
  ctx.beginPath();ctx.strokeStyle=c;ctx.lineWidth=1.5;ctx.arc(6,0,7,-1.2,1.2);ctx.stroke();
  line([8.5,-6.5],[8.5,6.5],c+'99',1);
  if(loaded){line([-1,0],[20,0],c,1.7);line([20,0],[16,-2],c,1.3);line([20,0],[16,2],c,1.3)}
  ctx.restore();
 }
}
function aimLabel(key){if(!key)return '';if(key.startsWith('rack:revive'))return '复活靶';if(key.startsWith('rack:'))return '得分靶';return name(key)}
function draw(){
 const f=frame();ctx.clearRect(0,0,1400,970);ctx.drawImage(background,0,0);
 if(showIntents)for(let p of f.players){
  if(p.status==='eliminated'||!p.intent?.goal)continue;
  const kind=p.intent.kind,goal=p.intent.goal,from=point(...p.position),to=point(...goal);
  if(!['pickup','gather','cache','revive','revive_snap','supply','pass','escape','batch_collect','batch_deliver','batch_stash'].includes(kind))continue;
  const color=kind==='cache'?'#93713588':COLORS[p.team]+'88';line(from,to,color,1.3,[5,5]);circle(...to,kind==='cache'?8:6,null,color);
  text(['pickup','batch_collect'].includes(kind)?`${name(p.id)} → 箭${p.intent.arrow}`:(intentLabels[kind]||({pass:'扔箭补给',supply:'补给',escape:'脱离踩点',revive_snap:'快踩快射'}[kind])||'移动'),to[0],to[1]-12,color.slice(0,7),10);
 }
 for(let b of f.arrows){
  const ground=point(...b.position);
  if(b.state==='ground'){circle(...ground,3,'#737b70');continue}
  const [vx,vy]=b.velocity,n=Math.hypot(vx,vy)||1;
  if(b.state==='flying'){
   const rise=Math.min(14,Math.max(0,b.position[2])*7),p=[ground[0],ground[1]-rise];
   circle(...ground,2,'#68716644');line([p[0]-vx/n*12,p[1]+vy/n*12],p,COLORS[b.shooter?.startsWith('attack')?'attack':'defense'],2);
   circle(...p,2.3,b.position[2]<.55?'#874a27':'#4c5c48');
   if(showHeights)text(`${b.position[2].toFixed(1)}m`,p[0]+10,p[1]-9,'#5b624e',10,'left');
  }else if(b.state==='tossed'){const p=[ground[0],ground[1]-Math.min(14,b.position[2]*7)];line([p[0]-vx/n*10,p[1]+vy/n*10],p,'#9d762f',2,[3,3]);circle(...ground,2,'#93784740');text('传',p[0]+7,p[1]-6,'#94712f',9)}else if(b.state==='discard_pending'){circle(...ground,2,'#a68b66')}else{
   const p=[ground[0],ground[1]-Math.min(5,Math.max(0,b.position[2])*25)];
   circle(...ground,2,'#93784740');line([p[0]-vx/n*8,p[1]+vy/n*8],p,'#ac8756',1.7);circle(...p,2,'#ac8756');
  }
 }
 for(let p of f.players){
  const out=p.status==='eliminated';const q=point(...(out?(p.out_position||p.position):p.position));const c=COLORS[p.team];
  if(out){
   if(p.out_stage==='hit'){person(q,c,p.crouched,false,true,p.team==='attack'?1:-1);circle(...q,17,null,'#bb503c');line([q[0]-6,q[1]-6],[q[0]+6,q[1]+6],'#a33f30',2);line([q[0]-6,q[1]+6],[q[0]+6,q[1]-6],'#a33f30',2);text('命中 · 弃箭',q[0],q[1]+20,'#a33f30',11)}
   else{person(q,c+'88',false,false,true,p.team==='attack'?1:-1);text(name(p.id),q[0],q[1]-28,'#8a8e80',10)}
   continue;
  }
  if(showMind&&p.mind_focus!==null&&p.mind_focus!==undefined){const spec=cfg.player_profiles[p.id];const half=.7+.7*(spec?.style?.attention_breadth??.5);ctx.fillStyle='#a58b3830';ctx.beginPath();ctx.moveTo(...q);ctx.arc(q[0],q[1],55,-p.mind_focus-half,-p.mind_focus+half);ctx.closePath();ctx.fill();text(`压力${Math.round((p.mind_pressure||0)*100)}`,q[0],q[1]+34,'#8d793e',9)}
  if(p.revive_runner)circle(...q,17,null,'#b68b32');person(q,c,p.crouched,p.bow_state==='ready',false,p.team==='attack'?1:-1,p.evasion_kind,p.dodge_velocity,p.bow_bearing);
  if(p.evasion_kind){const [vx,vy]=p.dodge_velocity,n=Math.hypot(vx,vy)||1;line([q[0]-vx/n*19,q[1]+vy/n*19],q,c+'85',2,[3,3]);circle(...q,13,null,c+'90')}
  if(p.aim_key&&p.aim_elapsed>0){const progress=Math.min(1,p.aim_elapsed/p.aim_required);ctx.beginPath();ctx.arc(q[0],q[1],11,-Math.PI/2,-Math.PI/2+progress*2*Math.PI);ctx.strokeStyle=c+'a0';ctx.lineWidth=2;ctx.stroke()}
  text(`${name(p.id)} · ${p.role==='revive_lane'&&p.objective==='score_battle'?'靶区支援':roleShort[p.role]}`,q[0],q[1]-30,c,11);
  let stage=p.stage==='gathering'?`集箭 ${p.ammo}/3`:p.stage==='caching'?`携 ${p.ammo} 支布箭`:p.intent.kind==='wait_delivery'?`等${name(p.job_partner)}补给`:p.intent.kind==='supply'?`送箭→${name(p.job_partner)}`:p.intent.kind==='pass'?`扔箭→${name(p.job_partner)}`:p.intent.kind==='pickup'?(p.job_partner&&p.role.startsWith('center')?`取箭→${name(p.job_partner)}`:'捡箭'):!p.ammo&&['request','search'].includes(p.intent.kind)?'缺箭 · 寻找可取箭':p.intent.kind==='escape'?'脱离踩点':p.bow_state==='nocking'?'搭箭中':p.bow_state==='ready'?`弓1 / 手${p.hand_arrows}`:`空弓 / 手${p.hand_arrows}`;
  if(p.intent.kind==='revive_snap')stage='点踩快射';else if(p.intent.kind==='revive')stage='踩点瞄准';
  if(p.intent.kind==='assess')stage='观察 · 等待机会';
  if(p.intent.kind==='track')stage='跟踪→'+aimLabel(p.aim_key);
  if(p.intent.kind==='shoot'||p.intent.kind==='shoot_low')stage=(p.intent.kind==='shoot_low'?'瞄下盘→':'瞄准→')+aimLabel(p.aim_key);
  if(p.intent.kind==='follow')stage='撒放 · 随动';
  const tactical={press_front:'前压 · 保持间隔',pin_hold:'架弓 · 压制末人',conserve:'控箭 · 保留火力',finish_target:'瞄得分靶',survive_cover:'退掩体 · 自保',survive_back:'退底线 · 自保',recover_front:'缺箭 · 补位观察'};
  if(tactical[p.intent.kind])stage=tactical[p.intent.kind];
  if(p.intent.kind==='batch_collect')stage=`后场回收 · 携${p.ammo}/${p.transport_quota||4}`;
  if(p.intent.kind==='batch_deliver')stage=`运箭→${name(p.job_partner)} · 携${p.ammo}`;
  if(p.intent.kind==='batch_pause')stage=`确认落点 · 携${p.ammo}`;
  if(p.intent.kind==='batch_stash')stage='布置备用箭';
  if(p.ammo_requested&&p.ammo<=1&&!p.intent.kind.startsWith('batch_'))stage+=' · 已请求补箭';
  if(p.intent.kind==='risk_hold')stage='评估风险 · 暂缓探身';
  if(p.evasion_kind)stage=p.evasion_kind==='duck'?'下潜闪避':'侧身闪避';
  text(stage,q[0],q[1]+20,'#566a55',10);
 }
 for(let e of data.cases[match].events){if(e.kind!=='release_cue'||time<e.t||time-e.t>.22)continue;const q=point(...e.position),to=point(...e.aim),n=Math.max(1,Math.hypot(to[0]-q[0],to[1]-q[1]));line([q[0]+(to[0]-q[0])/n*12,q[1]+(to[1]-q[1])/n*12],[q[0]+(to[0]-q[0])/n*22,q[1]+(to[1]-q[1])/n*22],'#c29649',2);}

 hud(f);
}
function events(){
 const el=$('#events');el.replaceChildren();
 for(let e of data.cases[match].events.filter(e=>['hit','rack_target','revive_granted','respawn','invalid_revive','opening_cache_ready','role_change','arrow_pass','team_mode','ammo_call','batch_start','batch_loaded','objective_shift'].includes(e.kind))){
  const row=document.createElement('div');row.className='event';
  const modeNames={balanced:'常规分路',lockdown:'人数优势 · 前压控箭',outnumbered:'人数劣势 · 复活或自保'};
  const msg=e.kind==='objective_shift'?'复活靶耗尽：转入靶区攻防':e.kind==='batch_start'?`${name(e.agent)} 开始后场批量回收`:e.kind==='batch_loaded'?`${name(e.agent)} 已携${e.ammo}支，转入分发`:e.kind==='team_mode'?`${e.team==='attack'?'红':'蓝'}队：${modeNames[e.mode]}`:e.kind==='ammo_call'?`${name(e.agent)} 提前请求补箭（持${e.ammo}支）`:e.kind==='role_change'?`${name(e.agent)} 补位 → ${roleShort[e.role]}`:e.kind==='arrow_pass'?`${name(e.agent)} 扔箭 → ${name(e.receiver)}`:e.kind==='hit'?`${name(e.shooter)} 命中 ${name(e.victim)}，离场排队`:e.kind==='rack_target'?`${name(e.shooter)} 击落${e.team==='attack'?'红':'蓝'}方得分靶 ${e.spot+1}`:e.kind==='revive_granted'?`${name(e.shooter)} 击落复活点 → ${name(e.agent)} 获得资格`:e.kind==='respawn'?`${name(e.agent)} 从底线重新入场`:e.kind==='opening_cache_ready'?`${name(e.agent)} 完成备用箭布置`:`${name(e.agent)} 复活射击无效`;
  row.textContent=`${fmt(e.t)}  ${msg}`;row.onclick=()=>{const after=data.cases[match].frames.find(f=>f.t>e.t);time=after?after.t:e.t;playing=false;$('#play').textContent='播放';draw()};el.appendChild(row);
 }
}
function playerProfiles(){const speeds=Object.values(cfg.roster).map(p=>p.muzzle_speed_fps),lo=Math.min(...speeds),hi=Math.max(...speeds);$('#fps-range').textContent=lo===hi?`${lo} FPS`:`${lo}–${hi} FPS`;const rating=(p,section,key)=>p.missing_fields?.includes(section+'.'+key)||p[section]?.[key]===undefined?'未知':Math.round(p[section][key]*100);const box=$('#profiles');box.replaceChildren();for(const [aid,p] of Object.entries(cfg.player_profiles)){const row=document.createElement('div');row.textContent=`${name(aid)} · ${p.player_id} · 打人评分 ${rating(p,'skills','body_accuracy')} / 打靶评分 ${rating(p,'skills','target_accuracy')} · 风险承担 ${rating(p,'style','risk_tolerance')} / 瞄准耐心 ${rating(p,'style','aim_patience')} · ${p.is_demo?'虚构示例':'未校准输入'}`;box.appendChild(row)}}
function selectMatch(i){match=i;time=0;playing=false;cachedFrameIndex=0;decodeCache.clear();lastDecodedIndex=-1;lastArrowTable=new Map();previousHud='';previousClock=-1;for(let k in boardCache)delete boardCache[k];$('#play').textContent='播放';$('#seek').max=data.cases[i].summary.duration_s;events();draw()}
data.cases.forEach((m,i)=>{let opt=document.createElement('option');opt.value=i;opt.textContent=m.label||`示例 ${i+1} · 种子 ${m.seed}`;$('#case').appendChild(opt)});
$('#case').onchange=e=>selectMatch(Number(e.target.value));
$('#play').onclick=()=>{if(time>=data.cases[match].summary.duration_s)time=0;playing=!playing;$('#play').textContent=playing?'暂停':'播放'};
$('#restart').onclick=()=>selectMatch(match);
$('#seek').oninput=e=>{time=Number(e.target.value);draw()};$('#speed').onchange=e=>speed=Number(e.target.value);
$('#intent-toggle').onchange=e=>{showIntents=e.target.checked;draw()};$('#mind-toggle').onchange=e=>{showMind=e.target.checked;draw()};
$('#height-toggle').onchange=e=>{showHeights=e.target.checked;draw()};
function tick(stamp){
 if(last!==null&&playing){
  time=Math.min(data.cases[match].summary.duration_s,time+Math.min(.25,(stamp-last)/1000)*speed);
  if(time>=data.cases[match].summary.duration_s){playing=false;$('#play').textContent='播放'}draw();
  frameWindows++;
  if(stamp-windowStart>=1000){$('#render-info').textContent=`回放 ${Math.round(frameWindows*1000/(stamp-windowStart))} FPS`;windowStart=stamp;frameWindows=0}
 }else{windowStart=stamp;frameWindows=0}
 last=stamp;requestAnimationFrame(tick);
}
staticField();playerProfiles();selectMatch(0);requestAnimationFrame(tick);
