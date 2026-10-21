"""Build reviewed figures and a compact report from reproducible episode logs."""

import argparse
from copy import deepcopy
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="runs/first_simulation/results.json")
    parser.add_argument("--output", default="reports/first_simulation")
    parser.add_argument("--heldout", default="runs/first_simulation/heldout_18_6.json")
    args = parser.parse_args()
    raw = json.loads(Path(args.input).read_text())
    if Path(args.heldout).exists() and not any(c["name"] == "heldout_rack_18_6" for c in raw["conditions"]):
        extra = json.loads(Path(args.heldout).read_text())
        assert extra["source_sha256"] == raw["source_sha256"]
        cc = extra["config_snapshot"]
        raw["conditions"].append({"name": extra["name"], "rack_xyz_m": cc["rack"]["position_xyz_m"], "attack_veterans": cc["teams"]["attack"]["veterans"], "defense_veterans": cc["teams"]["defense"]["veterans"], "dt_s": cc["time"]["dt_s"], "policy": cc["policy"], "spot_radius_m": cc["rack"]["spot_radius_m"], "summary": extra["summary"], "episodes": extra["episodes"]})
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    primary = raw["conditions"][:3]
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    labels = [f"ATK {c['attack_veterans']} veterans / DEF {c['defense_veterans']} veterans" for c in primary]
    rates = [c["summary"]["attack_win_rate"] * 100 for c in primary]
    errors = [[rates[i] - c["summary"]["wilson_95"][0] * 100 for i, c in enumerate(primary)], [c["summary"]["wilson_95"][1] * 100 - rates[i] for i, c in enumerate(primary)]]
    ax.barh(labels, rates, color=["#4279a8", "#d27f53", "#7a699b"], xerr=errors, capsize=4, height=0.55)
    ax.axvline(50, color="#666666", linestyle="--", linewidth=1)
    for i, c in enumerate(primary):
        ax.text(rates[i] + errors[1][i] + 1, i, f"{rates[i]:.1f}%  (n={c['summary']['episodes']})", va="center", fontsize=10)
    ax.set(xlim=(0, 100), xlabel="Attack win rate (%) with 95% Wilson interval", title="Assumed rear rack at (21.5, 6.0) m | 4v4 | 120 s")
    ax.invert_yaxis()
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, 0.015, "Scripted policies and unmeasured parameters; not a real-world win-rate estimate", ha="center", fontsize=9, color="#666666")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "roster_win_rates.png", dpi=160)
    plt.close(fig)

    grid = np.full((3, 3), np.nan)
    sizes = np.zeros((3, 3), dtype=int)
    xs, ys = [18.0, 20.0, 21.5], [2.5, 6.0, 9.5]
    for c in raw["conditions"]:
        if c["name"] == "equal_2v2_veterans" or c["name"].startswith("rack_"):
            x, y, _ = c["rack_xyz_m"]
            grid[ys.index(y), xs.index(x)] = c["summary"]["attack_win_rate"] * 100
            sizes[ys.index(y), xs.index(x)] = c["summary"]["episodes"]
    fig, ax = plt.subplots(figsize=(7.8, 5.4))
    img = ax.imshow(grid, origin="lower", vmin=0, vmax=100, cmap="RdBu_r", aspect="auto")
    ax.set_xticks(range(3), [f"{x:g}" for x in xs])
    ax.set_yticks(range(3), [f"{y:g}" for y in ys])
    ax.set(xlabel="Rack x-coordinate (m)", ylabel="Rack y-coordinate (m)", title="Exploratory rack-position scan | two veterans per team")
    for j in range(3):
        for i in range(3):
            if np.isfinite(grid[j, i]):
                ax.text(i, j, f"{grid[j,i]:.1f}%\nn={sizes[j,i]}", va="center", ha="center", color="white" if grid[j, i] < 25 or grid[j, i] > 75 else "#222222", fontsize=12)
    fig.colorbar(img, ax=ax, label="Attack win rate (%)")
    fig.text(0.5, 0.015, "Small exploratory samples; candidate positions require independent validation", ha="center", fontsize=9, color="#666666")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "rack_heatmap.png", dpi=160)
    plt.close(fig)

    compact = {k: v for k, v in raw.items() if k != "conditions"}
    compact["conditions"] = [{k: v for k, v in c.items() if k != "episodes"} | {"seeds": [r["seed"] for r in c["episodes"]]} for c in raw["conditions"]]
    (out / "summary.json").write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n")

    rows = ["| 阵容：攻方老手 / 守方老手 | 局数 | 攻方胜率 | 95% Wilson 区间 | 平均局长 | 平均剩余靶点 |", "| --- | ---: | ---: | --- | ---: | ---: |"]
    for c in primary:
        s = c["summary"]
        rows.append(f"| {c['attack_veterans']} / {c['defense_veterans']} | {s['episodes']} | {s['attack_win_rate']:.1%} | {s['wilson_95'][0]:.1%}–{s['wilson_95'][1]:.1%} | {s['mean_duration_s']:.1f} 秒 | {s['mean_remaining_spots']:.2f} |")
    grid_rows = ["| 靶架坐标 (x,y)，米 | 局数 | 攻方胜率 | 95%区间 |", "| --- | ---: | ---: | --- |"]
    for c in raw["conditions"]:
        if c["name"] == "equal_2v2_veterans" or c["name"].startswith("rack_"):
            s = c["summary"]
            grid_rows.append(f"| ({c['rack_xyz_m'][0]:g}, {c['rack_xyz_m'][1]:g}) | {s['episodes']} | {s['attack_win_rate']:.1%} | {s['wilson_95'][0]:.1%}–{s['wilson_95'][1]:.1%} |")
    checks = ["| 敏感性条件 | 局数 | 攻方胜率 | 95%区间 |", "| --- | ---: | ---: | --- |"]
    for c in raw["conditions"]:
        if c not in primary and not c["name"].startswith("rack_") and not c["name"].startswith("heldout_"):
            s = c["summary"]
            checks.append(f"| {c['name']} | {s['episodes']} | {s['attack_win_rate']:.1%} | {s['wilson_95'][0]:.1%}–{s['wilson_95'][1]:.1%} |")
    count = sum(c["summary"]["episodes"] for c in raw["conditions"])
    validation = next((c for c in raw["conditions"] if c["name"] == "heldout_rack_18_6"), None)
    if validation:
        v = validation["summary"]
        validation_text = f"候选靶位(18,6)米使用独立种子10000–10199验证：{v['attack_wins']}/{v['episodes']}局攻方获胜，即 **{v['attack_win_rate']:.1%}**，95%区间 **{v['wilson_95'][0]:.1%}–{v['wilson_95'][1]:.1%}**。这些种子未用于选择靶位；结果仍只针对当前脚本与未校准参数，不证明现实平衡，也不保证整个区间落入45%–55%。"
    else:
        validation_text = "尚未运行独立验证。"
    report = f'''# 首轮攻防仿真：23×12 米

这是 **{count} 局脚本对局**的条件性结果。没有真人校准，没有训练 RL 策略；统计区间只描述当前模型的 Monte Carlo 不确定性。

## 已知尺寸与假设

- 用户给定：场地23×12米；同一块靶架正面0.75×0.75米，五孔相对位置固定。
- 掩体原始输入有歧义，暂按1×0.6×1米解释。草图坐标不是实测：攻方掩体(6.5,2.5)、(8,6)、(6.5,9.5)，守方掩体(16.2,6)。
- 默认靶架中心(21.5,6,1.1)米，面朝攻方；孔直径17厘米、中心偏移与安装高度均是假设。
- 4v4，120秒；攻方持弓无箭，中场共4支，每人首次最多领取1支；守方每人配给5支，携带3支、出生区留下2支。
- 攻方无限复活，守方每人2条命；复活等待3秒且不补箭；接箭关闭，清完五孔才算攻方胜；超时守方胜。
- 暂定攻方移动至x=15米，守方从x=15.5米开始；新攻防模式取箭后不要求回到底线。
- 新手eta范围[0.15,0.45]，老手[0.65,0.95]；角度误差、瞄准/搭箭速度按eta映射。跑速3m/s，箭速25m/s，均未实测。
- 脚本：攻方三人优先清靶、一人优先压制，守方攻击可见敌人。脚本仅使用局部观测及公开地图，不使用敌人eta或隐藏位置。

完整参数见 [配置](../../configs/attack_defense_23x12.json)。

![暂定场地](layout.png)

## 默认后场靶位：阵容对比

{chr(10).join(rows)}

![阵容胜率](roster_win_rates.png)

这些条件必须分别看，不能将不同阵容汇总成50%就宣称公平。老手增加与策略选择同时影响结果；不能把该表外推到所有战术或真人水平。

## 靶架位置扫描

仅改变靶架平面坐标，五孔内部布局、场地、能力分布和其他规则保持一致。守方脚本的驻守点会根据公开靶位调整，因此结果包含守方的固定适应规则，而不是完全冻结的站位。

{chr(10).join(grid_rows)}

![靶位扫描](rack_heatmap.png)

这是探索性扫描，不是已验证的最优位置。大部分格子仅40局，且多个位置复用了种子；不能把格子当作相互独立样本，也不能仅凭最接近50%的格子判定平衡。

## 候选靶位的独立验证

{validation_text}

## 数值和假设敏感性

{chr(10).join(checks)}

敏感性条件使用相同的独立种子区间5000起；每项样本小，只能发现明显风险，不能证明步长已收敛或参数不重要。0.05秒步长仍用0.3秒策略决策间隔。曲线与碰撞在短时间段内以扫掠线段近似，不能取代真实弹道校准。

## 单局示例与资源

示例使用首个主实验种子1000，而非筛选最佳局。曲线记录地面、携带、飞行箭数与累计射击；每支箭保持唯一ID，总数始终24。没有完成的回合清靶时间保持为空，不将120秒当作实际清靶时间。

![单局中间时刻](demo_snapshot.png)

![箭矢资源](resources.png)

掩体利用率是每秒采样、存在敌人时至少一条敌我身体视线被挡的玩家时间比例，只是代理指标。当前低掩体和脚本前压行为可能导致利用率很低，不代表真人掩体无用。

## 复现

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/run_initial_experiments.py
PYTHONPATH=src python scripts/build_initial_report.py
```

Colab入口：[01_attack_defense.ipynb](../../notebooks/01_attack_defense.ipynb)。默认20局/阵容用于快速试跑，可增加样本。

模型源文件SHA256：`{raw['source_sha256']}`。配置快照、各条件差异、种子和统计量见 [summary.json](summary.json)。原始回合日志在运行输出目录，默认不纳入Git。

## 下一步

先确认掩体实际长宽高、五孔直径、区域界线、复活耗时与是否保留全歼胜利；再测量箭速和不同熟练度的散布。选定候选靶位后，用新种子与不同攻守策略验证，然后再研究弹药/生命/复活补偿。
'''
    (out / "README.md").write_text(report)
    print("Built report and figures:", out)


if __name__ == "__main__":
    main()
