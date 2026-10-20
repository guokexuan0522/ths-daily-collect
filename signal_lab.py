# -*- coding: utf-8 -*-
"""M3.5 信号实验室：对多套候选入场信号逐一回测，对着随机基线验真伪。

方法论（与 backtest.py 完全一致的交易规则，只换入场信号）：
- 信号：T-1 日因子 → T 日收盘成交
- 持仓：等权≤3只，持有5日，止损-5%/止盈+8%
- 流动性门槛：成交额>2亿（与实时选股一致），剔除ST/次新(<60根)/弹性<2%
- 随机基线：同门槛、同规则、固定种子，作为"最低门槛"——信号必须跑赢它才算有alpha
"""
import time
import numpy as np
import backtest as B

z, names = B.load()
codes = list(z["codes"]); dates = list(z["dates"])
C, H, L, V = z["C"], z["H"], z["L"], z["V"]
N, T = C.shape
is_st = np.array([("ST" in names.get(c, "").upper()) or ("退" in names.get(c, ""))
                  for c in codes])
F = B.precompute(z)
print("因子预计算完成: %d只 x %d天, %.0fs" % (N, T, time.time() - 0))

# ---- 扩展因子 ----
hi20 = B.roll_max(H, 20)
lo20 = -B.roll_max(-L, 20)            # roll_min
vol20 = B.roll_mean(V, 20)
vr20 = V / np.maximum(vol20, 1)      # 量比(20日)
hi10 = B.roll_max(H, 10)
was_high = hi10 >= 0.97 * hi20        # 近10日曾逼近20日高
chg1 = F["chg1"]; chg5 = F["chg5"]; chg20 = F["chg20"]
amp20 = F["amp20"]; e12 = F["e12"]; e50 = F["e50"]
ma5 = F["ma5"]; ma10 = F["ma10"]; ma20 = F["ma20"]
vol_ratio = F["vol_ratio"]; pos60 = F["pos60"]
bear = F["bear"]; amt = F["amt"]

LIQ = 2e8  # 成交额>2亿

def base_ok(t):
    return ((~is_st) & (amp20[:, t] >= 0.02) & (C[:, t] > 1.0) & (amt[:, t] >= LIQ))

# ---- 候选信号：返回 (score[N], ok[N])，score 越大越优先 ----
def s_oversold(t):
    ok = base_ok(t) & (chg20[:, t] > -0.25) & (chg20[:, t] < -0.01) & (chg1[:, t] > 0) & (bear[:, t] == 0)
    return -chg20[:, t] + (chg1[:, t] * 0.5), ok          # 最超跌(且今日转涨)优先

def s_pullback(t):
    ok = base_ok(t) & was_high[:, t] & (C[:, t] <= e12[:, t] * 1.02) & (C[:, t] >= e50[:, t]) \
         & (e12[:, t] > e50[:, t]) & (vr20[:, t] < 0.85) & (bear[:, t] == 0)
    return -(C[:, t] / np.maximum(e12[:, t], 1e-9)), ok    # 回踩到EXPMA12且缩量优先

def s_base_break(t):
    ok = base_ok(t) & (amp20[:, t] >= 0.02) & (amp20[:, t] <= 0.04) & (C[:, t] >= 0.97 * hi20[:, t]) \
         & (chg5[:, t] > 0) & (chg5[:, t] < 0.12) & (vol_ratio[:, t] >= 1.2) & (vol_ratio[:, t] <= 2.5) & (bear[:, t] == 0)
    return (C[:, t] / np.maximum(hi20[:, t], 1e-9)) - amp20[:, t] * 5, ok   # 低位横盘+近新高优先

def s_vol_launch(t):
    ok = base_ok(t) & (vol_ratio[:, t] >= 2.5) & (np.abs(chg20[:, t]) < 0.10) & (bear[:, t] == 0) & (C[:, t] > e50[:, t])
    return vol_ratio[:, t], ok                           # 放量但价格未涨(滞后启动)优先

def s_reversal(t):
    ok = base_ok(t) & (chg5[:, t] < 0) & (chg1[:, t] > 0) & (bear[:, t] == 0) & (C[:, t] > e50[:, t])
    return chg1[:, t] - chg5[:, t], ok                   # 下跌后首日转涨(反转)优先

def s_filt_mom(t):
    ok = base_ok(t) & (chg20[:, t] >= 0.05) & (chg20[:, t] <= 0.12) & (C[:, t] <= 0.97 * hi20[:, t]) \
         & (ma5[:, t] > ma10[:, t]) & (ma10[:, t] > ma20[:, t]) & (e12[:, t] > e50[:, t]) \
         & (bear[:, t] == 0) & (vol_ratio[:, t] >= 1.0) & (vol_ratio[:, t] <= 2.5)
    return chg20[:, t] * 10 + (1 - pos60[:, t]) * 5, ok  # 中温动量(不着顶)+未透支位置优先

SIGNALS = {
    "S1超跌反弹": s_oversold,
    "S2回踩支撑": s_pullback,
    "S3横盘突破": s_base_break,
    "S4放量启动": s_vol_launch,
    "S5反转确认": s_reversal,
    "S6过滤动量": s_filt_mom,
}

def make_pick(fn):
    def pick(t, need, F, V, is_st, rng):
        sc, ok = fn(t)
        if not ok.any():
            return []
        idx = np.where(ok)[0]
        s = sc[idx]
        order = idx[np.argsort(-s)]
        return list(order[:need])
    return pick

def random_pick(t, need, F, V, is_st, rng):
    elig = np.where(base_ok(t))[0]
    if len(elig) == 0:
        return []
    return list(rng.choice(elig, size=min(need, len(elig)), replace=False))

start = B.START_IDX
results = []
# 随机基线
r_ret, r_tr = B.simulate(random_pick, F, C, V, is_st, codes, names, dates, start, T)
rm = B.metrics_from(r_tr, r_ret, "随机基线")
results.append(rm)
for name, fn in SIGNALS.items():
    ret, tr = B.simulate(make_pick(fn), F, C, V, is_st, codes, names, dates, start, T)
    results.append(B.metrics_from(tr, ret, name))

# ---- 汇总表 ----
print("\n%-14s %10s %7s %9s %9s %9s %9s %9s" % ("信号", "组合收益%", "胜率%", "单笔期望%", "盈亏比", "最大回撤%", "交易笔", "平均持仓"))
for m in sorted(results, key=lambda x: -x["组合总收益%"]):
    print("%-14s %+10.1f %7.1f %+9.3f %9s %9.1f %9d %9.1f" % (
        m["标签"], m["组合总收益%"], m["胜率%"], m["单笔期望%"],
        m["盈亏比"] if m["盈亏比"] is not None else "-", m["最大回撤%"], m["总交易笔数"], m["平均持仓天数"]))
rb = next(m for m in results if m["标签"] == "随机基线")
win = [m for m in results if m["标签"] != "随机基线" and m["组合总收益%"] > rb["组合总收益%"]]
print("\n随机基线组合收益 = %+.1f%% (胜率%.1f%%)" % (rb["组合总收益%"], rb["胜率%"]))
print("跑赢随机的信号: %s" % ([w["标签"] for w in win] if win else "无（全部跑输随机）"))
