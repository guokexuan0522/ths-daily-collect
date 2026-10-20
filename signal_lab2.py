# -*- coding: utf-8 -*-
"""M3.5 鲁棒性验证：S3胜出后，确认它不过拟合；并给出流动性等权基准作对照。"""
import time
import numpy as np
import backtest as B

z, names = B.load()
codes = list(z["codes"]); dates = list(z["dates"])
C, H, L, V = z["C"], z["H"], z["L"], z["V"]
N, T = C.shape
is_st = np.array([("ST" in names.get(c, "").upper()) or ("退" in names.get(c, "")) for c in codes])
F = B.precompute(z)
hi20 = B.roll_max(H, 20); vol20 = B.roll_mean(V, 20); vr20 = V / np.maximum(vol20, 1)
chg5 = F["chg5"]; vol_ratio = F["vol_ratio"]; amp20 = F["amp20"]; bear = F["bear"]; amt = F["amt"]
LIQ = 2e8
start = B.START_IDX

def base_ok(t):
    return ((~is_st) & (amp20[:, t] >= 0.02) & (C[:, t] > 1.0) & (amt[:, t] >= LIQ))

# 流动性等权买入持有基准（每日起码在流动性池里的票等权，日收益=这些票平均日涨跌）
eq_ret = []
for t in range(start + 1, T):
    ok = base_ok(t - 1)
    idx = np.where(ok)[0]
    if len(idx):
        rr = (C[idx, t] / C[idx, t - 1] - 1)
        eq_ret.append(float(np.nanmean(rr)))
eq_curve = np.cumprod(1 + np.array(eq_ret))
print("流动性等权买入持有基准: %+.1f%%   (区间 %s~%s, %d日)" % ((eq_curve[-1]-1)*100, dates[start], dates[T-1], len(eq_ret)))

def s3(amp_hi, near_hi, vr_lo, vr_hi, t):
    ok = base_ok(t) & (amp20[:, t] >= 0.02) & (amp20[:, t] <= amp_hi) & (C[:, t] >= near_hi * hi20[:, t]) \
         & (chg5[:, t] > 0) & (chg5[:, t] < 0.12) & (vol_ratio[:, t] >= vr_lo) & (vol_ratio[:, t] <= vr_hi) & (bear[:, t] == 0)
    return (C[:, t] / np.maximum(hi20[:, t], 1e-9)) - amp20[:, t] * 5, ok

def run_pick(fn):
    def pick(t, need, F, V, is_st, rng):
        sc, ok = fn(t)
        if not ok.any(): return []
        idx = np.where(ok)[0]; order = idx[np.argsort(-sc[idx])]
        return list(order[:need])
    return pick

print("\n%-40s %10s %7s %9s %9s" % ("S3 参数变体", "组合收益%", "胜率%", "单笔期望%", "最大回撤%"))
variants = [
    ("基准(2-4%振幅/近高97%/量比1.2-2.5)", 0.04, 0.97, 1.2, 2.5),
    ("宽振幅(2-5%)",                   0.05, 0.97, 1.2, 2.5),
    ("宽振幅(2-6%)",                   0.06, 0.97, 1.2, 2.5),
    ("近高95%",                        0.04, 0.95, 1.2, 2.5),
    ("近高98%",                        0.04, 0.98, 1.2, 2.5),
    ("量比1.0-3.0",                    0.04, 0.97, 1.0, 3.0),
    ("量比1.5-3.0",                    0.04, 0.97, 1.5, 3.0),
    ("去掉量比约束",                    0.04, 0.97, 0.0, 99.0),
]
for label, ah, nh, vl, vh in variants:
    def fn(t, ah=ah, nh=nh, vl=vl, vh=vh):
        return s3(ah, nh, vl, vh, t)
    ret, tr = B.simulate(run_pick(fn), F, C, V, is_st, codes, names, dates, start, T)
    m = B.metrics_from(tr, ret, label)
    print("%-40s %+10.1f %7.1f %+9.3f %9.1f" % (label, m["组合总收益%"], m["胜率%"], m["单笔期望%"], m["最大回撤%"]))
