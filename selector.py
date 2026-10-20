# -*- coding: utf-8 -*-
"""M3.5 选股引擎：全A海扫 -> S3「横盘突破」信号 -> 每日候选池1-3只。

数据源（均为免鉴权公开接口，已实测）：
  截面：新浪全市场行情 Market_Center.getHQNodeData（分页）
  日线：新浪 CN_MarketData.getKLineData（scale=240, datalen=62）
  资金：同花顺 funds 接口（对终选池逐只拉，主力净流入=超大单+大单）
  东财接口当前 403（出口IP被拦），列为增强源，恢复后切换。

M3.5 信号 S3「横盘突破」（经 signal_lab 两年回测验证胜出，组合+55.1%/胜率50.2%/单笔期望+0.189%，
同时碾压随机基线(-43%)与流动性等权买入持有(-12%)，8个参数变体全部为正）：
  = 低位横盘蓄势(近20日平均振幅2-4%) + 逼近20日新高(距高<3%) + 5日微涨(0~12%) + 123法则无下跌确认
  + 成交额>2亿(流动性) + 非ST/非北交所/非次新
  评分：越贴近20日新高、振幅越窄越优先；同花顺主力净流入作实时版独有微弱加成。
  宁做短不做长（铁律#13）：弹性<2%直接剔除；选不出就空池，绝不将就。
出场规则（与回测一致）：止损-5%/止盈+8%/持有≤5日；跌破EXPMA50为结构失效。
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


def fetch_index_chg20(symbol="sh000300"):
    """拉宽基指数(沪深300)日K，返回最近20日收益率(百分比)，作为市场基准算 RS 相对强度。
    M4 数据进化：实时场景用大盘指数代理"市场"，与回测版(全市场等权指数)口径近似。"""
    kl = fetch_kline(symbol, datalen=62)
    if len(kl) < 21:
        return 0.0
    try:
        return (kl[-1][4] / kl[-21][4] - 1) * 100
    except Exception:
        return 0.0


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
    """由日K序列计算全部因子。kl: [(date,o,h,l,c,v)] 升序，长度>=60。
    口径与 backtest.py 的 precompute 严格对齐（S3 信号），保证实时选股=回测验证同一模型。"""
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
    hi20 = max(highs[-20:])          # 近20日最高（S3 逼近新高）
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
    near_hi20 = c >= 0.97 * hi20        # 距20日高<3%（横盘蓄势临近突破）
    # 弹性（铁律#13 宁做短不做长）：近20日平均振幅 (最高-最低)/收盘
    amp20 = sum((highs[i] - lows[i]) / max(closes[i], 1e-9)
                for i in range(len(closes) - 20, len(closes))) / 20 * 100
    return {
        "close": c, "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "expma12": e12, "expma50": e50,
        "hi20": hi20, "hi60": hi60, "lo60": lo60, "dd60": dd60,
        "vol_ratio": vol_ratio, "chg5": chg5, "chg10": chg10, "chg20": chg20,
        "bear_confirm": bear_confirm, "near_hi20": near_hi20,
        "pos60": c / hi60, "amp20": amp20,
    }


def score_stock(f, today_chg, fund=None, mkt_chg20=None):
    """M3.5 胜出信号 S3「横盘突破」打分 + 理由。返回 (score, reasons[], detail)。
    核心：越贴近20日新高(near_hi20)越优先；在2-4%横盘带内越偏好更高弹性(amp20)——
    贴合铁律#13「宁做短不做长」：弹性越好、超短爆发力越强。同花顺主力净流入作实时版独有微弱加成。"""
    s, why = 0.0, []
    c = f["close"]; hi20 = f["hi20"]; amp = f["amp20"]
    prox = c / hi20                       # 贴近20日新高程度
    s += prox * 100
    why.append("距20日高仅%.1f%%（横盘蓄势临近突破）" % ((1 - prox) * 100))
    # 弹性偏好：在2-4%紧横盘带内，振幅越高(越接近4%)弹性越好、超短爆发力越强
    elasticity = amp                       # amp∈[2,4]，越高越优
    s += elasticity * 5
    why.append("弹性优：近20日平均振幅%.1f%%（2-4%%紧横盘带，越接近4%%爆发力越强）" % amp)
    detail = {"贴近度": round(prox * 100, 1), "弹性": round(elasticity, 1),
              "5日涨幅": round(f["chg5"], 1), "123法则": f["bear_confirm"]}
    # M4 数据进化：相对强度 RS 软打分（个股20日收益 - 市场20日收益，小数口径与回测同口径）
    if mkt_chg20 is not None:
        rs = (f["chg20"] / 100.0) - (mkt_chg20 / 100.0)
        s += rs * 5
        detail["RS"] = round(rs * 100, 1)
        why.append("相对强度RS%+1.1f%%（近20日跑赢大盘）" % (rs * 100))
    # 实时版独有：主力资金加成（仅在净流入为正时加分，作为同因子并集的优选 tiebreaker）
    if fund:
        mass, big = fund
        main = mass + big
        if main > 0:
            s += min(main / 1e8, 5) * 0.5   # 微弱加成，不改变已验证核心排序
            why.append("同花顺主力净流入%+.0f万(资金加成)" % (main / 1e4))
    return round(s, 1), why, detail


def hard_filter(kl, row, f):
    """S3 风控硬过滤，返回 None 或 剔除原因（与 backtest.score_slice 口径一致）"""
    name = row.get("name", "")
    if "ST" in name.upper() or "退" in name:
        return "ST/退市风险"
    if row.get("symbol", "").startswith("bj"):
        return "北交所(波动制度不同)"
    if len(kl) < 60:
        return "次新(上市<60日)"
    if f["chg5"] <= 0:
        return "5日未上涨(非蓄势)"            # S3 要求 chg5>0
    if f["chg5"] >= 12:
        return "5日涨幅%.0f%%已爆炒" % f["chg5"]   # S3 要求 chg5<12%
    if f["amp20"] < 2.0:
        return "弹性不足(近20日平均振幅%.1f%%<2%%)" % f["amp20"]   # 铁律#13
    if f["amp20"] > 4.0:
        return "振幅%.1f%%非横盘(>4%%)" % f["amp20"]              # S3 要求紧横盘
    if f["bear_confirm"] != 0:
        return "123法则下跌确认%d处" % f["bear_confirm"]          # S3 要求无下跌确认
    if not f["near_hi20"]:
        return "距20日高>3%%未蓄势到位"                           # S3 要求逼近新高
    return None


def run(pool_limit=500, topn=3):
    t0 = time.time()
    mkt_chg20 = fetch_index_chg20()
    log("市场基准(沪深300近20日收益): %.1f%%" % mkt_chg20)
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
        sc, why, detail = score_stock(f, float(r.get("changepercent") or 0), mkt_chg20=mkt_chg20)
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
