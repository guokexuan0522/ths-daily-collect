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
    F["hi20"] = roll_max(H, 20)          # 近20日最高（S3 逼近新高用）
    F["C"] = C                            # 收盘价（score_slice 复用）
    F["amt"] = V * C                      # 成交额(元)
    # 123法则下跌确认计数（向量化近似）
    prev_lo = roll_max(-L, 10) * -1       # 近10日最低
    hi10 = roll_max(H, 10)
    hi_prev10 = np.zeros_like(C)
    for t in range(20, T):  # t<20 时前段不足20日，置0（不影响后续因子，START_IDX=60起用）
        hi_prev10[:, t] = H[:, t - 20:t - 10].max(axis=1)
    F["bear"] = ((C < prev_lo).astype(np.int8)
                 + (hi10 < hi_prev10).astype(np.int8)
                 + ((C < F["ma20"]) & (F["ma5"] < F["ma10"])).astype(np.int8))
    return F


def score_slice(F, t, is_st):
    """M3.5 胜出信号 S3「横盘突破」：低位横盘蓄势 + 逼近20日新高 + 无下跌确认。
    经 signal_lab 验证：组合+55.1% / 胜率50.2% / 单笔期望+0.189%，
    同时碾压随机基线(-43%)与流动性等权买入持有(-12%)，8个参数变体全部为正。
    返回 (scores, mask_ok)；score 仅用于同日内排序。"""
    tm = t - 1
    c = F["C"][:, tm]
    hi20 = F["hi20"][:, tm]
    amp = F["amp20"][:, tm]            # 小数(0.03=3%)
    c5 = F["chg5"][:, tm]             # 小数
    bear = F["bear"][:, tm]
    amt = F["amt"][:, tm]
    near_hi = c >= 0.97 * hi20        # 距20日高<3%
    ok = (~is_st & (amp >= 0.02) & (amp <= 0.04)
          & (c5 > 0) & (c5 < 0.12) & near_hi & (bear == 0)
          & (c > 1.0) & (amt >= 2e8))
    # 评分：越贴近20日新高越优先；在2-4%紧横盘带内越偏好更高弹性(amp)——
    # 贴合铁律#13「宁做短不做长」：弹性越好、超短爆发力越强（与实时 selector 对齐）
    score = (c / np.maximum(hi20, 1e-9)) + amp * 5
    return score, ok


def simulate(pick_fn, F, C, V, is_st, codes, names, dates, start, T):
    """事件驱动模拟：统一交易规则（等权≤3只/持有5日/止损-5%止盈+8%）。
    pick_fn(t, need) -> 当日 t 希望建仓的标的索引列表（≤need）。返回 (daily_ret, trades)。"""
    positions = []; daily_ret = []; trades = []
    rng = np.random.default_rng(20261020)
    for t in range(start, T - 1):
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
        if positions:
            r = float(np.mean([C[p["i"], t] / C[p["i"], t - 1] - 1 for p in positions]))
        else:
            r = 0.0
        daily_ret.append(r)
        if t + 1 >= T - 1:
            break
        need = TOP_PICKS - len(positions)
        if need > 0:
            for i in pick_fn(t, need, F, V, is_st, rng):
                positions.append({"i": int(i), "buy": float(C[i, t + 1]),
                                  "buy_t": t + 1, "days": 0})
    return daily_ret, trades


def model_pick(t, need, F, V, is_st, rng):
    """S3 模型选股：在 ok 集合内取评分最高的 need 只（与 signal_lab 口径一致，
    不再叠加'成交额前250'额外池限制——那会误剔真正的中盘突破股）。"""
    scores, ok = score_slice(F, t + 1, is_st)
    if not ok.any():
        return []
    idx = np.where(ok)[0]
    order = idx[np.argsort(-scores[idx])]
    return list(order[:need])


def random_pick(t, need, F, V, is_st, rng):
    """随机基线（同流动性门槛/同规则，固定种子，可复现）：
    与模型在同一'成交额>2亿'宇宙内随机选，确保公平对照。"""
    ok = (~is_st) & (F["amp20"][:, t] >= 0.02) & (F["C"][:, t] > 1.0) \
         & (F["amt"][:, t] >= 2e8) & (V[:, t] > 0)
    elig = np.where(ok)[0]
    if len(elig) == 0:
        return []
    return list(rng.choice(elig, size=min(need, len(elig)), replace=False))


def metrics_from(trades, daily_ret, label):
    rets = np.array([x["ret_pct"] for x in trades]) if trades else np.array([0.0])
    wins = rets[rets > 0]; losses = rets[rets <= 0]
    equity = np.cumprod(1 + np.array(daily_ret))
    peak = np.maximum.accumulate(equity)
    max_dd = float((equity / peak - 1).min() * 100) if len(equity) else 0
    return {
        "标签": label,
        "总交易笔数": len(trades),
        "胜率%": round(float(len(wins) / len(rets) * 100), 1) if len(rets) else 0,
        "平均盈利%": round(float(wins.mean()), 2) if len(wins) else 0,
        "平均亏损%": round(float(losses.mean()), 2) if len(losses) else 0,
        "盈亏比": round(float(wins.mean() / abs(losses.mean())), 2) if len(wins) and len(losses) else None,
        "单笔期望%": round(float(rets.mean()), 3),
        "组合总收益%": round(float((equity[-1] - 1) * 100), 1) if len(equity) else 0,
        "最大回撤%": round(max_dd, 1),
        "平均持仓天数": round(float(np.mean([x["days"] for x in trades])), 1) if trades else 0,
    }


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

    start = START_IDX
    # 模型 v1
    m_ret, m_tr = simulate(model_pick, F, C, V, is_st, codes, names, dates, start, T)
    # 随机基线（同规则，固定种子，可复现）
    r_ret, r_tr = simulate(random_pick, F, C, V, is_st, codes, names, dates, start, T)
    # 基准：流动性等权买入持有（与模型同一'成交额>2亿'宇宙，公平对照）
    # 用中位数（非均值）避免个别极端日收益拉爆序列（均值会虚报+388%）
    liq = (F["amt"] >= 2e8) & (~is_st[:, None]) & (F["C"] > 1.0)
    daily = C[:, start + 1:T] / np.maximum(C[:, start:T - 1], 1e-9) - 1
    bench = np.nanmedian(np.where(liq[:, start + 1:T], daily, np.nan), axis=0)
    bench = bench[~np.isnan(bench)]
    bench_eq = np.cumprod(1 + bench)
    m_eq = np.cumprod(1 + np.array(m_ret))
    r_eq = np.cumprod(1 + np.array(r_ret))

    metrics = metrics_from(m_tr, m_ret, "量化模型v2(S3横盘突破)")
    metrics["区间"] = "%s ~ %s" % (dates[start], dates[T - 1])
    metrics["交易日数"] = T - 1 - start
    metrics["基准(流动性等权)%"] = round(float((bench_eq[-1] - 1) * 100), 1)
    metrics["止损占比%"] = round(float(sum(1 for x in m_tr if x["reason"] == "止损") / max(len(m_tr), 1) * 100), 1)
    metrics["止盈占比%"] = round(float(sum(1 for x in m_tr if x["reason"] == "止盈") / max(len(m_tr), 1) * 100), 1)
    metrics["耗时秒"] = round(time.time() - t0, 1)
    random_metrics = metrics_from(r_tr, r_ret, "随机基线(同规则)")

    out = {
        "metrics": metrics,
        "random_baseline": random_metrics,
        "trades": m_tr,
        "equity_curve": [round(float(x), 4) for x in m_eq[::5]],
        "random_curve": [round(float(x), 4) for x in r_eq[::5]],
        "bench_curve": [round(float(x), 4) for x in bench_eq[::5]],
        "assumptions": "T-1收盘信号,T日收盘成交;等权≤3只;持有5日;止损-5%/止盈+8%;无资金流历史故回测版无资金因子;随机基线同规则固定种子可复现",
    }

    def _to_native(o):
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(str(type(o)))

    (DIR / "backtest.json").write_text(json.dumps(out, ensure_ascii=False, default=_to_native), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("\n随机基线对照:", json.dumps(random_metrics, ensure_ascii=False))
    print("已写入 backtest.json，模型交易明细 %d 笔 / 随机 %d 笔" % (len(m_tr), len(r_tr)))
    return out


if __name__ == "__main__":
    run()
