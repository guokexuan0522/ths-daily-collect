# -*- coding: utf-8 -*-
"""M2 选股引擎 MVP：全A海扫 -> 多因子打分 -> 每日候选池1-3只。

数据源（均为免鉴权公开接口，已实测）：
  截面：新浪全市场行情 Market_Center.getHQNodeData（分页）
  日线：新浪 CN_MarketData.getKLineData（scale=240, datalen=62）
  资金：同花顺 funds 接口（对终选池逐只拉，主力净流入=超大单+大单）
  东财接口当前 403（出口IP被拦），列为增强源，恢复后切换。

因子（0-100加权，全部透明可解释；v3.0 起重构，铁律#13 弹性入模）：
  动量20 趋势25(EXPMA/均线排列) 量能12 位置12 形态确认8 弹性13(近20日平均振幅) 资金10
  弹性硬门槛：近20日平均振幅<2% 直接剔除（宁做短不做长，选不出就不做）
  风控硬过滤：ST/退/北交所/次新(<60根K线)/60日回撤>50%/5日涨幅>25%/当日涨幅>7%
铁律#3：每只输出入选理由+买入条件+止损位+目标位+失效条件。
"""
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DIR = Path(__file__).resolve().parent
OUT = DIR / "picks.json"
LOG = DIR / "selector.log"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://finance.sina.com.cn/"}
THS_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
          "Referer": "https://stockpage.10jqka.com.cn/"}


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%F %T"), msg)
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _get(url, headers=UA, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def fetch_market():
    """新浪全市场行情 -> list of dict（约5400只，分页拉取）"""
    rows, page = [], 1
    while page <= 60:
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/"
               "json_v2.php/Market_Center.getHQNodeData?page=%d&num=100"
               "&sort=amount&asc=0&node=hs_a" % page)
        try:
            batch = json.loads(_get(url))
        except Exception as e:
            log("全市场第%d页失败: %r" % (page, e))
            break
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.15)
    log("全市场截面: %d 只" % len(rows))
    return rows


def fetch_kline(symbol, datalen=62):
    """新浪日K -> list[(date, o,h,l,c,v)] 按日期升序"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d"
           % (symbol, datalen))
    try:
        data = json.loads(_get(url))
    except Exception:
        return []
    out = []
    for r in data:
        out.append((r["day"], float(r["open"]), float(r["high"]),
                    float(r["low"]), float(r["close"]), float(r["volume"])))
    return out


def fetch_fund_ths(code, market):
    """同花顺资金流（复用 ths_common 已验证路径 fundsData.largeOrderFlow）。
    marketId 映射经实测：深市33；沪市先试17、备选22。"""
    import ths_common as C
    for mid in (("33",) if market == "sz" else ("17", "22")):
        f = C.fetch_funds(code, mid)
        if f:
            m = f.get("mass_capital_net_inflow") or 0
            b = f.get("big_capital_net_inflow") or 0
            if m or b:          # 零值视为无效，继续尝试下一个 marketId
                return (m, b)
    return None


def ema(closes, n):
    k = 2.0 / (n + 1)
    e = closes[0]
    for c in closes[1:]:
        e = c * k + e * (1 - k)
    return e


def calc_factors(kl):
    """由日K序列计算全部因子。kl: [(date,o,h,l,c,v)] 升序，长度>=60"""
    closes = [r[4] for r in kl]
    highs = [r[2] for r in kl]
    lows = [r[3] for r in kl]
    vols = [r[5] for r in kl]
    c = closes[-1]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    e12 = ema(closes[-30:], 12)
    e50 = ema(closes[-60:], 50)
    hi60 = max(highs[-60:])
    lo60 = min(lows[-60:])
    dd60 = (hi60 - lo60) / hi60
    vol_ratio = (vols[-1] / (sum(vols[-6:-1]) / 5)) if sum(vols[-6:-1]) else 1
    chg5 = (c / closes[-6] - 1) * 100 if closes[-6] else 0
    chg10 = (c / closes[-11] - 1) * 100 if len(closes) > 10 and closes[-11] else 0
    chg20 = (c / closes[-21] - 1) * 100 if len(closes) > 20 and closes[-21] else 0
    # 123法则简化：近20日下跌确认信号计数（破前低+不创新高）
    prev_hi = max(highs[-20:-10])
    recent_hi = max(highs[-10:])
    prev_lo = min(lows[-20:-10])
    bear_confirm = 0
    if c < prev_lo:
        bear_confirm += 1          # 跌破前低
    if recent_hi < prev_hi:
        bear_confirm += 1          # 反弹不创新高
    if c < ma20 and ma5 < ma10:
        bear_confirm += 1          # 均线走坏
    new_high20 = c >= max(highs[-20:]) * 0.995
    # 弹性（铁律#13 宁做短不做长）：近20日平均振幅 (最高-最低)/收盘
    amp20 = sum((highs[i] - lows[i]) / max(closes[i], 1e-9)
                for i in range(len(closes) - 20, len(closes))) / 20 * 100
    return {
        "close": c, "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "expma12": e12, "expma50": e50,
        "hi60": hi60, "lo60": lo60, "dd60": dd60,
        "vol_ratio": vol_ratio, "chg5": chg5, "chg10": chg10, "chg20": chg20,
        "bear_confirm": bear_confirm, "new_high20": new_high20,
        "pos60": c / hi60, "amp20": amp20,
    }


def score_stock(f, today_chg, fund=None):
    """打分 + 理由。返回 (score, reasons[], detail)
    v3.0 权重（铁律#13 弹性入模）：动量20 趋势25 量能12 位置12 形态8 弹性13 资金10 = 100"""
    s, why = 0.0, []
    # 动量20（20日涨幅5-15%最佳，>25%扣）
    m = max(0, 20 - abs(f["chg20"] - 10) * 1.0)
    s += m
    if 3 <= f["chg20"] <= 18:
        why.append("20日动量%+.1f%%处于强势区" % f["chg20"])
    # 趋势25
    t = 0
    if f["expma12"] > f["expma50"]:
        t += 10
        why.append("EXPMA12>EXPMA50多头")
    if f["close"] > f["expma12"]:
        t += 5
        why.append("价格站稳EXPMA12(%.2f)" % f["expma12"])
    if f["ma5"] > f["ma10"] > f["ma20"]:
        t += 10
        why.append("三线战法：MA5>MA10>MA20多头排列")
    s += t
    # 量能12
    v = 0
    vr = f["vol_ratio"]
    if 1.5 <= vr <= 3.5:
        v = 12
        why.append("量比%.2f温和放量" % vr)
    elif 1.0 <= vr < 1.5:
        v = 6
    s += v
    # 位置12
    p = 0
    if f["pos60"] < 0.75:
        p = 12
        why.append("位置低（60日高点下方%.0f%%）有空间" % ((1 - f["pos60"]) * 100))
    elif f["pos60"] < 0.9:
        p = 6
    s += p
    # 形态确认8
    k = 0
    if f["bear_confirm"] == 0:
        k += 4
        why.append("123法则无下跌确认信号")
    if f["new_high20"]:
        k += 4
        why.append("创20日新高")
    s += k
    # 弹性13（铁律#13 宁做短不做长：近20日平均振幅）
    amp = f["amp20"]
    e = 0
    if amp >= 4:
        e = 13
        why.append("弹性优：近20日平均振幅%.1f%%" % amp)
    elif amp >= 3:
        e = 10
        why.append("弹性良：近20日平均振幅%.1f%%" % amp)
    elif amp >= 2:
        e = 6
    s += e
    # 资金10
    if fund:
        mass, big = fund
        main = mass + big
        if main > 0:
            s += 10
            why.append("同花顺主力净流入%+.0f万" % (main / 1e4))
    detail = {"动量": round(m, 1), "趋势": t, "量能": v, "位置": p,
              "形态": k, "弹性": e}
    return round(s, 1), why, detail


def hard_filter(kl, row, f):
    """风控硬过滤，返回 None 或 剔除原因"""
    name = row.get("name", "")
    if "ST" in name.upper() or "退" in name:
        return "ST/退市风险"
    if row.get("symbol", "").startswith("bj"):
        return "北交所(波动制度不同)"
    if len(kl) < 60:
        return "次新(上市<60日)"
    if f["dd60"] > 0.5:
        return "60日回撤%.0f%%阴跌股" % (f["dd60"] * 100)
    if f["chg5"] > 25:
        return "5日涨幅%.0f%%爆炒" % f["chg5"]
    if f["amp20"] < 2.0:
        return "弹性不足(近20日平均振幅%.1f%%<2%%)" % f["amp20"]   # 铁律#13
    return None


def run(pool_limit=250, topn=3):
    t0 = time.time()
    market = fetch_market()
    # 第一层：截面筛选（非ST/非北交所/成交额门槛/当日涨幅区间），按成交额排序取前pool_limit
    cand = []
    for r in market:
        try:
            amt = float(r.get("amount") or 0)
            chg = float(r.get("changepercent") or 0)
        except Exception:
            continue
        name = r.get("name", "")
        if "ST" in name.upper() or "退" in name:
            continue
        if r.get("symbol", "").startswith("bj"):
            continue
        if amt < 2e8:            # 成交额<2亿剔除
            continue
        if chg > 7 or chg < -3:   # 不追高、不接下落的刀
            continue
        cand.append(r)
    cand.sort(key=lambda x: float(x.get("amount") or 0), reverse=True)
    cand = cand[:pool_limit]
    log("第一层截面筛选: %d 只入池（全市场%d）" % (len(cand), len(market)))

    # 第二层：日线因子 + 打分
    scored = []
    for i, r in enumerate(cand):
        sym = r["symbol"]
        kl = fetch_kline(sym)
        if len(kl) < 60:
            continue
        f = calc_factors(kl)
        reason = hard_filter(kl, r, f)
        if reason:
            continue
        sc, why, detail = score_stock(f, float(r.get("changepercent") or 0))
        scored.append({
            "code": r["code"], "name": r["name"], "symbol": sym,
            "price": float(r["trade"]), "chg": float(r.get("changepercent") or 0),
            "amount_yi": float(r.get("amount") or 0) / 1e8,
            "score": sc, "why": why, "detail": f, "factors": detail,
        })
        if (i + 1) % 50 == 0:
            log("  进度 %d/%d 已得分 %d 只" % (i + 1, len(cand), len(scored)))
        time.sleep(0.05)
    log("第二层因子打分完成: %d 只，耗时%.0fs" % (len(scored), time.time() - t0))

    # 终选：前6名补同花顺资金流加成后排序
    scored.sort(key=lambda x: x["score"], reverse=True)
    finalists = scored[:6]
    for r in finalists:
        fund = fetch_fund_ths(r["code"], r["symbol"][:2])
        if fund:
            mass, big = fund
            main = mass + big
            r["fund_main"] = main
            if main > 0:
                r["score"] = round(r["score"] + 10, 1)
                r["why"].append("同花顺主力净流入%+.0f万(资金加成)" % (main / 1e4))
            else:
                r["why"].append("同花顺主力净流出%+.0f万(无加成)" % (main / 1e4))
        else:
            r["fund_main"] = None
            r["why"].append("同花顺资金流未取到(无加成)")
        time.sleep(1.0)
    finalists.sort(key=lambda x: x["score"], reverse=True)

    # 生成完整操作方案
    picks = []
    for i, r in enumerate(finalists[:topn + 2]):
        d = r["detail"]
        buy_retrace = round(d["expma12"], 2)
        stop = round(r["price"] * 0.95, 2)
        target1 = round(r["price"] * 1.08, 2)
        target2 = round(r["price"] * 1.12, 2)
        invalid_stop = round(d["expma50"], 2)
        picks.append({
            "rank": i + 1,
            "primary": i < topn,
            "code": r["code"], "name": r["name"],
            "price": r["price"], "chg": r["chg"],
            "score": r["score"],
            "factors": r["factors"],
            "reasons": r["why"],
            "buy": "回踩EXPMA12(%.2f)或5日线(%.2f)缩量不破低吸；放量突破今日最高%.2f可追（需盘中确认）"
                   % (buy_retrace, d["ma5"], r["price"] if r["chg"] >= 0 else r["price"]),
            "stop": "买入价-5%%(%.2f)或跌破EXPMA50(%.2f)，二选一先到先执行" % (stop, invalid_stop),
            "target": "第一目标%.2f(+8%%)；第二目标%.2f(+12%%)或60日高点%.2f附近" % (target1, target2, d["hi60"]),
            "invalid": "①跌破EXPMA50且放量 ②主力净流入连续2日转负 ③买入后5个交易日未脱离成本3%%以上",
            "amount_yi": round(r["amount_yi"], 2),
            "fund_main": r.get("fund_main"),
            "amp20": round(d["amp20"], 2),
        })
    result = {
        "generated_at": datetime.now().strftime("%F %T"),
        "market_scanned": len(market),
        "layer1_pool": len(cand),
        "layer2_scored": len(scored),
        "data_source": "新浪全市场+新浪日K+同花顺资金流(东财当前403降级)",
        "elapsed_sec": round(time.time() - t0, 1),
        "picks": picks,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log("选股完成: 候选%d只(主推%d)，写入 picks.json，总耗时%.0fs"
        % (len(picks), topn, time.time() - t0))
    return result


if __name__ == "__main__":
    import sys
    pool = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    res = run(pool_limit=pool)
    for p in res["picks"]:
        tag = "★主推" if p["primary"] else " 备选"
        print("%s #%d %s %s 得分%.1f | %s"
              % (tag, p["rank"], p["code"], p["name"], p["score"],
                 "；".join(p["reasons"][:3])))
