"""Create a plain, blank 18-player collection workbook and matching CSVs."""
from pathlib import Path
import csv,json,sys
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,Alignment
from openpyxl.worksheet.datavalidation import DataValidation

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from archery_tag_balance.player_model import SKILLS,STYLE

LABELS={'body_accuracy':'打人准度','target_accuracy':'打靶准度','reaction':'来箭反应','agility':'闪避动作控制','pickup':'拾取熟练度','nocking':'搭箭熟练度','carry_control':'额外携箭控制','endurance':'体能恢复','risk_tolerance':'愿意承担风险','aim_patience':'偏好长瞄准','cover_preference':'偏好守掩体','target_preference':'偏好打靶','attention_breadth':'自觉关注范围','scan_frequency':'习惯主动转移观察'}
SCENARIOS=[
('S01','掩体后空手，后方2米有箭；队友预计3秒能送达。','自己去捡','等队友送','先观察再定','其他'),
('S02','队友出局，自己有箭，正面有威胁、侧面有人架弓。','尝试踩点快射','等队友压制后行动','继续守当前岗位','其他'),
('S03','准备射复活靶，怀疑侧面会在自己出手前后撒放。','先预判时间差并安排横移','先看侧面再决定','先打靶再观察','其他'),
('S04','高掩体后有箭，探身能打靶，但有一名已知强射手在侧面。','短探快射','继续守住观察','换角度再射','其他'),
('S05','手上有备用箭，附近队友缺箭，自己也有较好射击机会。','先完成射击','先补给队友','提醒对方自取','其他'),
('S06','比赛剩15秒，本方落后；前出有机会复活队友，但很危险。','立即尝试','等待掩护再尝试','继续当前打法','其他'),
('S07','同样位置被两名不同选手分别架弓：一名很熟悉、一名很少交手。','分别评估两个人','主要看位置和距离','主要看自己当时状态','其他'),
('S08','刚向正面射完一箭，侧面还有可能的威胁。','横移并看侧面','前后移动并看侧面','先看箭结果','其他')]


def main():
    data=ROOT/'data';data.mkdir(exist_ok=True);wb=Workbook();wb.remove(wb.active)
    instructions=[['用途','收集个人能力、风格、具体局面选择。不是自动生成实力排名。'],['填写','真实玩家的评分全部留空。0—100是自评/他评量表，不直接代表命中概率。'],['未知','留空代表未知，不要填0。请记录来源、评估人和把握程度。'],['多份评分','自评与他评分别追加行，不覆盖原记录；导入时指定来源。'],['场景','每人回答8个情境，并写为什么这样选。没有标准答案。'],['装备','箭速记录对应弓、箭重、拉距和撒放组合，不能当作全体统一值。'],['演示','配置中的DEMO参数是虚构示例，不是任何群友的真实资料。'],['导入','python -X utf8 scripts/import_player_data.py --workbook data/player_collection.xlsx --output configs/player_profiles_imported.json'],['运行','python -X utf8 scripts/build_suzhou.py --profiles configs/player_profiles_imported.json'],['观测','模拟行为CSV均标为simulation；真实录像观测填video_observations.csv。']]
    sheets={
      '说明':instructions,
      '选手信息':[['player_id|选手编号','alias|别名','role|常用位置','source|来源','rater_id|评估人','notes|备注','carry_count|习惯总携箭数1到4']]+[[f'P{i:02d}','','','','','',''] for i in range(1,19)],
      '技术能力':[['player_id|选手编号']+[k+'|'+LABELS[k] for k in SKILLS]+['source|自评他评测量','rater_id|评估人','confidence|把握程度','notes|依据']]+[[f'P{i:02d}']+['']*(len(SKILLS)+4) for i in range(1,19)],
      '打法风格':[['player_id|选手编号']+[k+'|'+LABELS[k] for k in STYLE]+['source|自评他评录像','rater_id|评估人','confidence|把握程度','notes|依据']]+[[f'P{i:02d}']+['']*(len(STYLE)+4) for i in range(1,19)],
      '对手认知':[['player_id|本人编号','opponent_id|对手编号','concern|主观威胁程度','source|来源','rater_id|评估人','notes|具体情形']]+[['']*6 for _ in range(30)],
      '局面选择':[['player_id|选手编号','scenario_id|情境编号','choice|选择A到D','risk|自己认为风险','gain|自己认为收益','attention|主要关注哪里','reason|为什么','source|来源']]+[[f'P{i:02d}',s[0],'','','','','',''] for i in range(1,19) for s in SCENARIOS],
      '情境题目':[['scenario_id|情境编号','question|情境','A','B','C','D']]+[list(s) for s in SCENARIOS],
      '器材记录':[['player_id|选手编号','bow|弓型号','draw_weight_lb|磅数','arrow_mass_g|箭重克','draw_length_in|拉距英寸','release|撒放','muzzle_speed_fps|箭速FPS','trials|测量次数','speed_sd_fps|速度标准差','source|来源','notes|备注']]+[[f'P{i:02d}']+['']*10 for i in range(1,19)],
      '状态自述':[['player_id|选手编号','match_id|比赛编号','stage|阶段','fatigue|疲劳0到100','pressure|压力0到100','confidence|信心0到100','pressure_effect|压力下更好更差不变','source|来源','notes|描述']]+[[f'P{i:02d}','',stage,'','','','','',''] for i in range(1,19) for stage in ['赛前','中段','残局']],
      '群聊速度摘录':[['record_id','arrow_mass_g','draw_weight_lb','bow','release','muzzle_speed_fps','status','notes'],['R01',56,30,'响尾蛇','未注明',139.6,'群聊自述待核验','拉距和测量条件未完整提供；不映射到任何玩家'],['R02',65,'','响尾蛇Pro美猎','传统扳指',134,'群聊自述待核验','不据此改变全体平均箭速'],['R03',65,'','响尾蛇Pro美猎','三指',133,'群聊自述待核验','拉距与重复测量信息待补充']],
      '指标说明':[['field','meaning','scale']]+[[k,LABELS[k],'0—100；不是直接概率'] for k in [*SKILLS,*STYLE]]+[['cover_geometry_s','模拟中位于己方掩体后方投影的时间','不是对全部敌方射线的真实遮挡时长'],['intended_body_hit_rate','指定打人目标接触数/已结束飞行的打人射箭数','无已结束射箭时留空；末尾在飞箭不当作失败'],['scoreboard_knockdown_rate','射得分靶的有效击落数/已结束飞行的射得分靶箭数','不等同于几何接触率'],['attention_breadth','自评关注广度；当前映射为有限观察锥','尚未用真人数据验证']]}
    for name,rows in sheets.items():
        ws=wb.create_sheet(name)
        for row in rows:ws.append(row)
        ws.freeze_panes='B2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:
            letter=col[0].column_letter;ws.column_dimensions[letter].width=24 if letter!='A' else 20
            for cell in col:cell.font=Font(name='Arial',size=11);cell.alignment=Alignment(vertical='top',wrap_text=True)
        if name in ('说明','情境题目','指标说明'):ws.column_dimensions['B'].width=80
        if name in ('技术能力','打法风格'):
            count=len(SKILLS) if name=='技术能力' else len(STYLE)
            dv=DataValidation(type='decimal',operator='between',formula1=0,formula2=100,allow_blank=True);dv.error='请输入0到100，未知请留空。';dv.showErrorMessage=True;ws.add_data_validation(dv)
            for j in range(2,count+2):dv.add(f'{ws.cell(1,j).column_letter}2:{ws.cell(1,j).column_letter}500')
    wb.save(data/'player_collection.xlsx')
    check=load_workbook(data/'player_collection.xlsx',data_only=False)
    assert all(check['技术能力'].cell(i,j).value is None for i in range(2,20) for j in range(2,10))
    for name,rows in sheets.items():
        if name in ('说明','指标说明','群聊速度摘录'):continue
        filename={'选手信息':'players','技术能力':'skills','打法风格':'styles','对手认知':'opponent_beliefs','局面选择':'situations','情境题目':'scenario_definitions','器材记录':'equipment','状态自述':'states'}[name]
        with (data/(filename+'.csv')).open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.writer(f);writer.writerow([str(s).split('|')[0] for s in rows[0]]);writer.writerows(rows[1:])
    with (data/'video_observations.csv').open('w',newline='',encoding='utf-8-sig') as f:
        csv.writer(f).writerow(['source','match_id','player_id','role','video_start_s','video_end_s','action','observed_result','observer_id','confidence','notes'])
    profiles={}
    for team in ['attack','defense']:
        for i in range(6):
            pid=f'P{1+i+(6 if team=="defense" else 0):02d}'
            style_values=[(.7,.2,.3,.2,.7,.7),(.25,.8,.9,.65,.3,.3),(.5,.5,.4,.4,.6,.6),(.7,.3,.4,.5,.7,.6),(.4,.65,.85,.8,.4,.4),(.8,.2,.2,.5,.55,.6)][i]
            if team=='defense' and i==1:style_values=(.8,.35,.3,.65,.75,.75)
            profiles[f'{team}_{i}']=dict(player_id=pid,alias='虚构示例'+pid,is_demo=True,source='synthetic_demo',skills={k:.75 for k in SKILLS},style=dict(zip(STYLE,style_values)),opponent_beliefs={'P07':.85,'P12':.3} if pid=='P02' else {})
    (ROOT/'configs/player_profiles_demo.json').write_text(json.dumps(profiles,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lineup={aid:p['player_id'] for aid,p in profiles.items()};(ROOT/'configs/lineup.json').write_text(json.dumps(lineup,indent=2)+'\n',encoding='utf-8')
    print('Created blank 18-player workbook, CSVs, and clearly marked synthetic demo profiles.')

if __name__=='__main__':main()
