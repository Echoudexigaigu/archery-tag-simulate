from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=ROOT/'src/archery_tag_balance/suzhou_renderer.js';s=p.read_text()
s=s.replace("revive_runner:!!p[6],out_position:","revive_runner:!!p[6],role:data.roles[p[13]],bow_state:['empty','nocking','ready'][p[14]],hand_arrows:p[15],out_stage:['hit','leaving','waiting','returning',null][p[16]],out_position:")
s=s.replace("state:['ground','flying','settling'][b[4]]","state:['ground','flying','settling','tossed','discard_pending'][b[4]],hand_throw:!!b[8]")
s=s.replace("JSON.stringify([f.racks,f.queue,f.approved,f.score])","JSON.stringify([f.racks,f.queue,f.approved,f.score,f.players.map(p=>[p.role,p.status])])")
s=s.replace("  drawBoard('#rack-revive','revive',f);", "  for(let role of data.roles)for(let team of ['attack','defense']){const p=f.players.find(p=>p.team===team&&p.role===role&&p.status==='active');$('#role-'+team+'-'+role).textContent=p?name(p.id):'空缺'}\n  drawBoard('#rack-revive','revive',f);")
s=s.replace("function draw(){", "const roleShort={high_flank:'高边',high_cover:'高掩',center_1:'中一',center_2:'中二',low_cover:'矮掩',revive_lane:'复活路'};\nfunction person(q,c,crouch,loaded,out=false){const h=crouch?14:23;circle(q[0],q[1],8.5,null,c+'45');rect(q[0]-6,q[1]-h+9,12,h-10,c);circle(q[0],q[1]-h+5,4.2,c);line([q[0]-4,q[1]-2],[q[0]-4,q[1]+2],c,2);line([q[0]+4,q[1]-2],[q[0]+4,q[1]+2],c,2);if(out)line([q[0]+6,q[1]-h+13],[q[0]+11,q[1]-h],c,2);else{ctx.beginPath();ctx.strokeStyle=c;ctx.lineWidth=1.4;ctx.arc(q[0]+6,q[1]-h+13,7,-1.2,1.2);ctx.stroke();if(loaded)line([q[0]+3,q[1]-h+13],[q[0]+17,q[1]-h+13],c,1.5)}}\nfunction draw(){")
s=s.replace("['pickup','gather','cache','revive'].includes(kind)","['pickup','gather','cache','revive','revive_snap','supply','pass','escape'].includes(kind)")
s=s.replace("intentLabels[kind],to[0]","(intentLabels[kind]||({pass:'扔箭补给',supply:'补给',escape:'脱离踩点',revive_snap:'快踩快射'}[kind])),to[0]")
s=s.replace("  }else{\n   line([ground[0]", "  }else if(b.state==='tossed'){const p=[ground[0],ground[1]-Math.min(14,b.position[2]*7)];line([p[0]-vx/n*10,p[1]+vy/n*10],p,'#9d762f',2,[3,3]);circle(...ground,2,'#93784740');text('传',p[0]+7,p[1]-6,'#94712f',9)}else if(b.state==='discard_pending'){circle(...ground,2,'#a68b66')}else{\n   line([ground[0]")
start=s.index(' for(let p of f.players){\n  if(p.status===\'eliminated\')');end=s.index('\n hud(f);',start)
s=s[:start]+''' for(let p of f.players){
  const out=p.status==='eliminated';const q=point(...(out?(p.out_position||p.position):p.position));const c=COLORS[p.team];
  if(out){
   if(p.out_stage==='hit'){person(q,c,p.crouched,false,true);circle(...q,17,null,'#bb503c');line([q[0]-6,q[1]-6],[q[0]+6,q[1]+6],'#a33f30',2);line([q[0]-6,q[1]+6],[q[0]+6,q[1]-6],'#a33f30',2);text('命中 · 弃箭',q[0],q[1]+20,'#a33f30',11)}
   else{person(q,c+'88',false,false,true);text(name(p.id),q[0],q[1]-28,'#8a8e80',10)}
   continue;
  }
  if(p.revive_runner)circle(...q,17,null,'#b68b32');person(q,c,p.crouched,p.bow_state==='ready');
  text(`${name(p.id)} · ${roleShort[p.role]}`,q[0],q[1]-30,c,11);
  let stage=p.stage==='gathering'?`集箭 ${p.ammo}/3`:p.stage==='caching'?`携 ${p.ammo} 支布箭`:p.intent.kind==='pass'?'扔箭补给':p.intent.kind==='pickup'?'捡箭':p.intent.kind==='escape'?'脱离踩点':p.bow_state==='nocking'?'搭箭中':p.bow_state==='ready'?`弓1 / 手${p.hand_arrows}`:`空弓 / 手${p.hand_arrows}`;
  if(p.intent.kind==='revive_snap')stage='点踩快射';else if(p.intent.kind==='revive')stage='踩点瞄准';
  text(stage,q[0],q[1]+20,'#566a55',10);
 }
 for(let e of data.cases[match].events){if(e.kind!=='release_cue'||time<e.t||time-e.t>.22)continue;const q=point(...e.position),to=point(...e.aim),n=Math.max(1,Math.hypot(to[0]-q[0],to[1]-q[1]));line([q[0]+(to[0]-q[0])/n*12,q[1]+(to[1]-q[1])/n*12],[q[0]+(to[0]-q[0])/n*22,q[1]+(to[1]-q[1])/n*22],'#c29649',2);}
''' +s[end:]
s=s.replace("'opening_cache_ready'].includes(e.kind)","'opening_cache_ready','role_change','arrow_pass'].includes(e.kind)")
s=s.replace("const msg=e.kind==='hit'?", "const msg=e.kind==='role_change'?`${name(e.agent)} 补位 → ${roleShort[e.role]}`:e.kind==='arrow_pass'?`${name(e.agent)} 扔箭补给`:e.kind==='hit'?")
s=s.replace("row.onclick=()=>{time=e.t;", "row.onclick=()=>{const after=data.cases[match].frames.find(f=>f.t>e.t);time=after?after.t:e.t;")
before=" text('俯视场地 · 箭矢高度参与碰撞判定',700,943,'#8b907d',12);"
after=""" for(let team of ['attack','defense']){const [wx,wy]=cfg.suzhou.waiting_positions_m[team];for(let i=0;i<6;i++){let p=point(wx+(i-2.5)*cfg.v3.waiting_spacing_m,wy);ctx.strokeStyle='#a7af9c';ctx.lineWidth=1;ctx.strokeRect(p[0]-10,p[1]-10,20,20)}}
 text('身高参照',1325,235,'#6b7964',11);for(let [x,h,label,color] of [[1285,1.7,'人','#667b60'],[1320,1.5,'高','#a0aa94'],[1355,.8,'矮','#a0aa94']]){rect(x-8,315-h*35,16,h*35,color);text(label,x,333,'#6b7964',10);text(h+'m',x,350,'#6b7964',9)}
 text('身宽 0.50m',1320,375,'#6b7964',10);
 text('实线射箭可命中 · 虚线扔箭始终无伤害 · 人物足下圈为真实占地',700,943,'#8b907d',12);"""
assert before in s;s=s.replace(before,after);p.write_text(s)
p=ROOT/'src/archery_tag_balance/suzhou_replay.html';s=p.read_text().replace('场地图校正 v2','V3 · 六岗位与箭支补给').replace('苏州赛 · 独立规则模拟','苏州 V3 · 岗位与补给')
start=s.index('<div class="warning">');end=s.index('</div>',start)+6
s=s[:start]+'<div class="warning">高边 · 高掩体 · 中一 · 中二 · 矮掩体 · 复活路。空弓可以搬运、扔箭；搭箭后可出手。观察岗位补位、补给路线、点踩快射与命中后的弃箭离场。</div>'+s[end:]
s=s.replace('暂以 3 支为持箭上限','总携箭上限 4 支（弓上最多 1 支、手上最多 3 支）')
s=s.replace('一箭有效首触命中即离场。','一箭有效首触命中即出局；画面有短暂停顿、就近弃箭，再举手离场。')
s=s.replace('<h3>离场队列与底线返回</h3>', '<h3>当前岗位</h3><table class="roles"><thead><tr><th>职责</th><th>红队</th><th>蓝队</th></tr></thead><tbody>'+''.join(f'<tr><td>{n}</td><td id="role-attack-{r}"></td><td id="role-defense-{r}"></td></tr>' for r,n in zip(['high_flank','high_cover','center_1','center_2','low_cover','revive_lane'],['高边','高掩体','中一','中二','矮掩体','复活路']))+'</tbody></table><h3>离场队列与底线返回</h3>')
s=s.replace('</style>','.roles{width:100%;border-collapse:collapse;margin:0 0 18px}.roles th,.roles td{padding:5px 10px;text-align:left;border-bottom:1px solid #e6e8df;font-size:13px}</style>')
s=s.replace('棕色：弹跳 / 滑行，已失效','棕色：手扔 / 弹跳 / 滑行，无伤害')
p.write_text(s)
p=ROOT/'OPEN_RULESETS.html';s=p.read_text().replace('场地图校正 v2','V3 · 岗位与箭支补给');p.write_text(s)
print('V3 UI upgraded')
