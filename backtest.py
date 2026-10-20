# -*- coding: utf-8 -*-
"""M3 回测引擎：对选股模型做 2024-10 ~ 2026-10 两年真实日线回测。

方法论（诚实声明）：
- 信号：T-1 日收盘因子选股 → T 日收盘价成交（无未来函数；收盘价成交略偏保守）
- 持仓：等权最多3只，持有5个交易日，止损-5%/止盈+8%（收盘价判定，日线精度）
- 回测版因子去掉"同花顺资金流"（无历史资金流数据，实时版才有），权重重分配：
  动量20 趋势25(EXPMA/均线) 量能15 位置15 形态10(123法则) 弹性15
- 弹性因子（铁律#13宁做短不做长）：近20日平均振幅，硬门槛<2%剔除
- 数据：history.npz（fetch_history.py 拉取的全市场500日K）
"""
import json
import time
from pathlib import Path

import numpy as np

DIR = Path(__file__).resolve().parent
HOLD_DAYS = 5
STOP = -0.05
TP = 0.08
TOP_POOL = 250          # 第一层入池数
TOP_PICKS = 3           # 主推只数
START_IDX = 60          # 因子窗口60日


def roll_mean(a, w):
    cs = np.cumsum(a, axis=1)
    out = np.empty_like(a)
    out[:, :w] = a[:, :w].mean(axis=1, keepdims=True)
    out[:, w:] = (cs[:, w:] - cs[:, :-w]) / w
    return out


def expma_full(a, n):
    k = 2.0 / (n + 1)
    e = a.copy()
    for t in range(1, a.shape[1]):
        e[:, t] = a[:, t] * k + e[:, t - 1] * (1 - k)
    return e


def roll_max(a, w):
    out = np.empty_like(a)
    for t in range(a.shape[1]):
        out[:, t] = a[:, max(0, t - w + 1):t + 1].max(axis=1)
    return out


def load():
    z = np.load(DIR / "history.npz", allow_pickle=True)
    names = json.loads((DIR / "history_names.json").read_text(encoding="utf-8"))
    return z, names


def precompute(z):
    C, H, L, V = z["C"], z["H"], z["L"], z["V"]
    N, T = C.shape
    F = {}
    F["chg1"] = np.zeros_like(C); F["chg1"][:, 1:] = C[:, 1:] / C[:, :-1] - 1
    F["chg5"] = np.zeros_like(C); F["chg5"][:, 5:] = C[:, 5:] / C[:, :-5] - 1
    F["chg20"] = np.zeros_like(C); F["chg20"][:, 20:] = C[:, 20:] / C[:, :-20] - 1
    F["ma5"] = roll_mean(C, 5)
    F["ma10"] = roll_mean(C, 10)
    F["ma20"] = roll_mean(C, 20)
    F["e12"] = expma_full(C, 12)
    F["e50"] = expma_full(C, 50)
    F["vol_ratio"] = V / np.maximum(roll_mean(V, 5), 1)
    F["pos60"] = C / np.maximum(roll_max(H, 60), 1e-9)
    F["amp20"] = roll_mean((H - L) / np.maximum(C, 1e-9), 20)
    F["amt"] = V * C                      # 成交额(元)
    # 123法则下跌确认计数（向量化近似）
    prev_lo = roll_max(-L, 10) * -1       # 近10日最低
    hi10 = roll_max(H, 10)
    hi_prev10 = np.zeros_like(C)
    for t in range(10, T):
        hi_prev10[:, t] = H[:, max(0, t - 20):t - 10].max(axis=1)
    F["bear"] = ((C < prev_lo).astype(np.int8)
                 + (hi10 < hi_prev10).astype(np.int8)
                 + ((C < F["ma20"]) & (F["ma5"] < F["ma10"])).astype(np.int8))
    return F


def score_slice(F, t, is_st):
    """t 日截面打分（用 t-1 日因子，t 即信号日）。返回 (scores, mask_ok)"""
    tm = t - 1
    chg20 = F["chg20"][:, tm]
    m20 = np.clip(1 - np.abs(chg20 - 0.10) * 1.2, 0, 1) * 20
    trend = ((F["e12"][:, tm] > F["e50"][:, tm]).astype(float) * 10
             + (F["C"][:, tm] > F["e12"][:, tm]).astype(float) * 5
             + ((F["ma5"][:, tm] > F["ma10"][:, tm]) &
                (F["ma10"][:, tm] > F["ma20"][:, tm])).astype(float) * 10)
    vr = F["vol_ratio"][:, tm]
    vol = np.where((vr >= 1.5) & (vr <= 3.5), 15, np.where((vr >= 1.0) & (vr < 1.5), 8, 0))
    pos = F["pos60"][:, tm]
    pos_s = np.where(pos < 0.75, 15, np.where(pos < 0.9, 8, 0))
    form = (F["bear"][:, tm] == 0).astype(float) * 5 + \
           (pos >= 0.995).astype(float) * 5
    # 弹性15：amp20 分位线性（前40%满分）
    amp = F["amp20"][:, tm]
    thr40 = np.quantile(amp, 0.60)
    elas = np.clip(amp / max(thr40, 1e-9), 0, 1) * 15
    total = m20 + trend + vol + pos_s + form + elas
    # 硬过滤
    ok = (~is_st
          & (F["amp20"][:, tm] >= 0.02)            # 弹性硬门槛（铁律#13）
          & (F["chg5"][:, tm] <= 0.25)             # 5日不爆炒
          & (F["C"][:, tm] > 1.0))                 # 剔除极低价
    return total, ok


def run():
    t0 = time.time()
    z, names = load()
    codes = list(z["codes"])
    dates = list(z["dates"])
    C = z["C"]; H = z["H"]; L = z["L"]; V = z["V"]
    N, T = C.shape
    is_st = np.array([("ST" in names.get(c, "").upper()) or ("退" in names.get(c, ""))
                      for c in codes])
    F = precompute(z)
    print("因子预计算完成: %d只 x %d天, %.0fs" % (N, T, time.time() - t0))

    trades = []
    positions = []          # {code_idx, buy_price, days}
    daily_ret = []
    start = START_IDX
    for t in range(start, T - 1):
        # 1) 平仓检查（用 t 日收盘）
        still = []
        for p in positions:
            p["days"] += 1
            ret = C[p["i"], t] / p["buy"] - 1
            exit_reason = None
            if ret <= STOP:
                exit_reason = "止损"
            elif ret >= TP:
                exit_reason = "止盈"
            elif p["days"] >= HOLD_DAYS:
                exit_reason = "到期"
            if exit_reason:
                trades.append({
                    "code": codes[p["i"]], "name": names.get(codes[p["i"]], ""),
                    "buy_date": dates[p["buy_t"]], "sell_date": dates[t],
                    "buy": round(float(p["buy"]), 2),
                    "sell": round(float(C[p["i"], t]), 2),
                    "ret_pct": round(ret * 100, 2), "days": p["days"],
                    "reason": exit_reason,
                })
            else:
                still.append(p)
        positions = still
        # 2) 当日组合收益（收盘到收盘）
        if positions:
            r = float(np.mean([C[p["i"], t] / C[p["i"], t - 1] - 1 for p in positions]))
        else:
            r = 0.0
        daily_ret.append(r)
        # 3) t+1 建仓信号（用 t 日因子）
        if t + 1 >= T - 1:
            break
        if len(positions) >= TOP_PICKS:
            continue
        scores, ok = score_slice(F, t + 1, is_st)
        # 第一层：成交额前 TOP_POOL
        amt = F["amt"][:, t]
        pool_mask = ok & (np.argsort(np.argsort(-amt)) < TOP_POOL)
        scores = np.where(pool_mask, scores, -1)
        top = np.argsort(-scores)[:TOP_PICKS - len(positions)]
        for i in top:
            if scores[i] <= 0:
                continue
            if any(p["i"] == i for p in positions):
                continue
            positions.append({"i": int(i), "buy": float(C[i, t + 1]),
                              "buy_t": t + 1, "days": 0})
    # 指标
    rets = np.array([x["ret_pct"] for x in trades]) if trades else np.array([0])
    wins = rets[rets > 0]; losses = rets[rets <= 0]
    equity = np.cumprod(1 + np.array(daily_ret))
    peak = np.maximum.accumulate(equity)
    max_dd = float((equity / peak - 1).min() * 100) if len(equity) else 0
    # 基准：全市场等权日收益
    bench = np.nanmean(C[:, start + 1:T] / np.maximum(C[:, start:T - 1], 1e-9) - 1, axis=0)
    bench_eq = np.cumprod(1 + bench)
    metrics = {
        "区间": "%s ~ %s" % (dates[start], dates[T - 1]),
        "交易日数": T - 1 - start,
        "总交易笔数": len(trades),
        "胜率%": round(float(len(wins) / len(rets) * 100), 1) if len(rets) else 0,
        "平均盈利%": round(float(wins.mean()), 2) if len(wins) else 0,
        "平均亏损%": round(float(losses.mean()), 2) if len(losses) else 0,
        "盈亏比": round(float(wins.mean() / abs(losses.mean())), 2) if len(wins) and len(losses) else None,
        "单笔期望%": round(float(rets.mean()), 3),
        "组合总收益%": round(float((equity[-1] - 1) * 100), 1) if len(equity) else 0,
        "基准(全市场等权)%": round(float((bench_eq[-1] - 1) * 100), 1),
        "最大回撤%": round(max_dd, 1),
        "平均持仓天数": round(float(np.mean([x["days"] for x in trades])), 1) if trades else 0,
        "止损占比%": round(float(sum(1 for x in trades if x["reason"] == "止损") / max(len(trades), 1) * 100), 1),
        "止盈占比%": round(float(sum(1 for x in trades if x["reason"] == "止盈") / max(len(trades), 1) * 100), 1),
        "耗时秒": round(time.time() - t0, 1),
    }
    out = {"metrics": metrics, "trades": trades,
           "equity_curve": [round(float(x), 4) for x in equity[::5]],  # 抽样存曲线
           "bench_curve": [round(float(x), 4) for x in bench_eq[::5]],
           "assumptions": "T-1收盘信号,T日收盘成交;等权≤3只;持有5日;止损-5%/止盈+8%;无资金流历史故回测版无资金因子"}
    (DIR / "backtest.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("已写入 backtest.json，交易明细 %d 笔" % len(trades))
    return out


if __name__ == "__main__":
    run()
