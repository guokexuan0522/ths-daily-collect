# -*- coding: utf-8 -*-
"""M4 实验框架 v3（决定性）：引入相对强度 RS 因子（数据进化）+ 多因子打分。

前两轮结论(v1/v2)：
  - S3 单笔期望≈0，靠频率+复利赚+37.5%；单纯 regime/放量过滤无法既提胜率又保收益。
  - 出场进化（结构失效/移动止盈）能把回撤 -38.7%→-14.7%、单笔期望转正，但胜率不升反降。
本轮聚焦"算法+数据进化"最后的提胜率希望——相对强度 RS：
  RS = 个股20日收益 - 全市场等权指数20日收益（个股相对市场的强弱）
  - 硬过滤 RS>0（只做"横盘蓄势且跑赢大盘"的强势突破，动量/相对强度效应）
  - 软打分 RS 加权（不改变 ok 集合，仅排序优先）
评估标准（可用性，胜率为辅）：组合>随机 & 回撤可控 & 前/后段均正 & 单笔期望>0。
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
e50 = F["e50"]; vol_ratio = F["vol_ratio"]; chg1 = F["chg1"]
print("因子预计算完成: %d只 x %d天" % (N, T))

# 市场状态 + 市场20日收益（EWIdx 等权指数）
amt = F["amt"]
liq = (amt >= 2e8) & (~is_st[:, None]) & (C > 1.0)
ew = np.full(T, np.nan)
for t in range(1, T):
    idx = np.where(liq[:, t - 1])[0]
    if len(idx):
        ew[t] = float(np.nanmean(C[idx, t] / C[idx, t - 1] - 1))
EWIdx = np.cumprod(np.where(np.isnan(ew), 1.0, 1 + ew))
e50_idx = B.expma_full(EWIdx[None, :], 50)[0]
regime = EWIdx > e50_idx
ew_chg20 = np.full(T, np.nan)
ew_chg20[20:] = EWIdx[20:] / EWIdx[:-20] - 1     # 市场20日收益
print("多头市场交易日占比: %.1f%%" % (regime.mean() * 100))


def score_slice(tm, is_st, rs_filter=False, rs_score=False):
    """S3 信号 + RS 进化。tm=决策日(与 backtest 口径一致)。"""
    c = F["C"][:, tm]; hi20 = F["hi20"][:, tm]; amp = F["amp20"][:, tm]
    c5 = F["chg5"][:, tm]; bear = F["bear"][:, tm]; amt_t = F["amt"][:, tm]
    near_hi = c >= 0.97 * hi20
    ok = (~is_st & (amp >= 0.02) & (amp <= 0.04) & (c5 > 0) & (c5 < 0.12)
          & near_hi & (bear == 0) & (c > 1.0) & (amt_t >= 2e8))
    rs = F["chg20"][:, tm] - ew_chg20[tm]          # 相对强度（个股-市场）
    if rs_filter:
        ok = ok & (rs > 0)                         # 只做跑赢大盘的强势突破
    score = (c / np.maximum(hi20, 1e-9)) + amp * 5
    if rs_score:
        score = score + rs * 5                     # RS 加权（不改变 ok 集合，仅排序）
    return score, ok


def make_pick(rs_filter, rs_score):
    def pick(t, need, F, V, is_st, rng):
        scores, ok = score_slice(t, is_st, rs_filter, rs_score)
        if not ok.any():
            return []
        idx = np.where(ok)[0]
        order = idx[np.argsort(-scores[idx])]
        return list(order[:need])
    return pick


def random_pick(t, need, F, V, is_st, rng):
    ok = (~is_st) & (F["amp20"][:, t] >= 0.02) & (F["C"][:, t] > 1.0) \
         & (F["amt"][:, t] >= 2e8) & (V[:, t] > 0)
    elig = np.where(ok)[0]
    if len(elig) == 0:
        return []
    return list(rng.choice(elig, size=min(need, len(elig)), replace=False))


def simulate_v2(pick_fn, exit_rule, regime_filter, start, T):
    STOP, TP, HOLD, TRAIL, MAXHOLD = -0.05, 0.08, 5, 0.03, 12
    positions = []; daily_ret = []; trades = []
    rng = np.random.default_rng(20261020)
    for t in range(start, T - 1):
        still = []
        for p in positions:
            p["days"] += 1
            ret = C[p["i"], t] / p["buy"] - 1
            p["peak"] = max(p["peak"], ret)
            exit_reason = None
            if ret <= STOP:
                exit_reason = "止损"
            elif exit_rule.get("trail") and (p["peak"] - ret) >= TRAIL:
                exit_reason = "移动止盈"
            elif (not exit_rule.get("trail")) and ret >= TP:
                exit_reason = "止盈"
            elif exit_rule.get("struct") and C[p["i"], t] < e50[p["i"], t]:
                exit_reason = "结构失效"
            elif p["days"] >= HOLD:
                exit_reason = "到期"            # 5日硬到期兜底（铁律#13 宁做短不做长）
            elif p["days"] >= MAXHOLD:
                exit_reason = "到期"
            if exit_reason:
                trades.append({
                    "code": codes[p["i"]], "name": names.get(codes[p["i"]], ""),
                    "buy_date": dates[p["buy_t"]], "sell_date": dates[t],
                    "buy_t": p["buy_t"],
                    "buy": round(float(p["buy"]), 2),
                    "sell": round(float(C[p["i"], t]), 2),
                    "ret_pct": round(ret * 100, 2), "days": p["days"],
                    "reason": exit_reason,
                })
            else:
                still.append(p)
        positions = still
        if positions:
            r = float(np.mean([C[p["i"], t] / C[p["i"], t - 1] - 1 for p in positions]))
        else:
            r = 0.0
        daily_ret.append(r)
        if t + 1 >= T - 1:
            break
        need = B.TOP_PICKS - len(positions)
        if need > 0:
            if regime_filter is not None and not regime_filter[t]:
                continue
            for i in pick_fn(t, need, F, V, is_st, rng):
                positions.append({"i": int(i), "buy": float(C[i, t + 1]),
                                  "buy_t": t + 1, "days": 0, "peak": 0.0})
    return daily_ret, trades


def analyze(daily_ret, trades, label):
    m = B.metrics_from(trades, daily_ret, label)
    eq = np.cumprod(1 + np.array(daily_ret))
    m["组合总收益%"] = round(float((eq[-1] - 1) * 100), 1)
    k = len(daily_ret) // 2
    eq1 = np.cumprod(1 + np.array(daily_ret[:k])); eq2 = np.cumprod(1 + np.array(daily_ret[k:]))
    m["前段收益%"] = round(float((eq1[-1] - 1) * 100), 1)
    m["后段收益%"] = round(float((eq2[-1] - 1) * 100), 1)
    bt = np.array([x["buy_t"] for x in trades]) if trades else np.array([])
    st = B.START_IDX
    def wr(mask):
        if not mask.any():
            return 0.0
        r = np.array([x["ret_pct"] for x in trades])[mask]
        return round(float((r > 0).mean() * 100), 1)
    m["前段胜率%"] = wr(bt < st + k); m["后段胜率%"] = wr(bt >= st + k)
    return m


start = B.START_IDX
print("\n===== M4 v3：RS 相对强度因子实验 =====")
experiments = [
    ("随机基线", random_pick, {"trail": False, "struct": False}, None, False, False),
    ("S3基线(M3.5)", make_pick(False, False), {"trail": False, "struct": False}, None, False, False),
    ("S3+RS硬过滤+结构失效", make_pick(True, False), {"trail": False, "struct": True}, None, True, False),
    ("S3+RS打分+结构失效", make_pick(False, True), {"trail": False, "struct": True}, None, False, True),
    ("S3+RS硬过滤+移动止盈", make_pick(True, False), {"trail": True, "struct": True}, None, True, False),
    ("S3+RS打分+移动止盈", make_pick(False, True), {"trail": True, "struct": True}, None, False, True),
    ("S3+RS硬过滤+regime+移动止盈", make_pick(True, False), {"trail": True, "struct": True}, regime, True, False),
]
rows = []
for label, fn, rule, rg, rf, rs in experiments:
    t0 = time.time()
    ret, tr = simulate_v2(fn, rule, rg, start, T)
    m = analyze(ret, tr, label)
    m["耗时秒"] = round(time.time() - t0, 1)
    rows.append(m)

print("\n%-34s %9s %6s %8s %7s %7s %6s %7s %6s %6s" % (
    "变体", "组合%", "胜率%", "单笔期望%", "回撤%", "笔数", "前段%", "后段%", "前胜%", "后胜%"))
for m in sorted(rows, key=lambda x: -x["组合总收益%"]):
    print("%-34s %+9.1f %6.1f %+8.3f %7.1f %7d %6.1f %7.1f %6.1f %6.1f" % (
        m["标签"], m["组合总收益%"], m["胜率%"], m["单笔期望%"], m["最大回撤%"],
        m["总交易笔数"], m["前段收益%"], m["后段收益%"], m["前段胜率%"], m["后段胜率%"]))
base = next(m for m in rows if m["标签"] == "S3基线(M3.5)")
rb = next(m for m in rows if m["标签"] == "随机基线")
print("\nS3基线组合=%.1f%% 随机=%.1f%%" % (base["组合总收益%"], rb["组合总收益%"]))
print("可用性达标(组合>随机 & 回撤<=-25 & 单笔期望>0 & 前/后段均正):")
for m in rows:
    ok = (m["组合总收益%"] > rb["组合总收益%"] and m["最大回撤%"] <= -25
          and m["单笔期望%"] > 0 and m["前段收益%"] > 0 and m["后段收益%"] > 0)
    print("  [%s] 胜率%.1f%% 组合%+1.1f%% 期望%+0.3f%% 回撤%+.1f%%   %s"
          % ("✓" if ok else "✗", m["胜率%"], m["组合总收益%"], m["单笔期望%"], m["最大回撤%"], m["标签"]))
