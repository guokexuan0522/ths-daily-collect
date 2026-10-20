# -*- coding: utf-8 -*-
"""持仓作战平台 v3.0 数据层：实时盯盘采集 + 四模块策略文本生成。

红涨绿跌（A股看盘习惯）。v3.0 起版面渲染委托 render_v3.render()。
四个作战模块（命名规范化，v2.0 起，v3.0 补盘后指令）：
  「分时做T指导」— 基于当日分时数据（均价/日内位置/量比），盘中实时调整
  「日线波段指导」— 基于日线数据（EXPMA/均线/支撑压力/123法则），盘中实时调整
  「盘后作战指令」— 明日/未来几日走留判断（浮盈浮亏阈值+趋势确认，附具体价位）
  「超短交易纪律」— 固定纪律条款，个性化数字
v3.0 修复：日线因子高低点取数错误（原 highs 误取 low、lows 误取 close，
  导致支撑/压力/60日高低/123法则全部失真）。
铁律#3：页面每个数字都可追溯到来源；无依据不出结论。
"""
import json
import time
import urllib.request
from pathlib import Path

DIR = Path(__file__).resolve().parent
POS_FILE = DIR / "positions.json"
LEDGER = DIR / "flows.jsonl"
PICKS_FILE = DIR / "picks.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://gu.qq.com/"}
VERSION = "v3.1"

REVISION_LOG = [
    ("v1.0", "2026-10-20", "持仓盯盘页上线：实时行情/盈亏/异动/60秒刷新"),
    ("v2.0", "2026-10-20", "①版本徽章+修订历史+铁律摘要 ②每只显示持仓数 ③原“做T预案”拆分为"
     "「分时做T指导」「日线波段指导」「超短交易纪律」三模块 ④新增每日选股候选池板块"),
]


def _get(url, headers=UA, timeout=12):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_quotes(markets_codes):
    q = ",".join(markets_codes)
    raw = _get("https://qt.gtimg.cn/q=" + q).decode("gbk", "ignore")
    out = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("v_") or "=\"" not in line:
            continue
        f = line.split("=\"", 1)[1].rstrip("\";").split("~")
        if len(f) < 50:
            continue
        def num(i):
            try:
                return float(f[i])
            except Exception:
                return None
        out[f[2]] = {
            "name": f[1], "code": f[2], "price": num(3), "pre_close": num(4),
            "vol_hand": num(6), "time": f[30] if len(f) > 30 else "",
            "chg_pct": num(32), "high": num(33), "low": num(34),
            "amt_wan": num(37), "turnover": num(38),
            "vol_ratio": (num(50) or 0) / 100.0 if num(50) else None,
        }
    return out


def fetch_kline(code, market):
    sym = "%s%s" % (market, code)
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=62" % sym)
    try:
        data = json.loads(_get(url, headers={"User-Agent": "Mozilla/5.0",
                                             "Referer": "https://finance.sina.com.cn/"}))
        return [(float(r["open"]), float(r["high"]), float(r["low"]),
                 float(r["close"]), float(r["volume"])) for r in data]
    except Exception:
        return []


def ema(closes, n):
    k = 2.0 / (n + 1)
    e = closes[0]
    for c in closes[1:]:
        e = c * k + e * (1 - k)
    return e


def limit_pct(code, name):
    if "ST" in name.upper():
        return 5.0
    if code.startswith("30") or code.startswith("688"):
        return 20.0
    return 10.0


def latest_fund_flows():
    best = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            cur = best.get(r["code"])
            if cur is None or r["trade_date"] >= cur["trade_date"]:
                best[r["code"]] = r
    return best


def fmt_wan(v):
    return "{:+,.2f}万".format(v / 1e4) if v is not None else "-"


def build_rows():
    pos = json.loads(POS_FILE.read_text(encoding="utf-8"))
    mc = ["%s%s" % (p["market"], p["code"]) for p in pos["positions"]]
    quotes = fetch_quotes(mc)
    funds = latest_fund_flows()
    rows = []
    for p in pos["positions"]:
        q = quotes.get(p["code"])
        if not q or not q.get("price"):
            continue
        kl = fetch_kline(p["code"], p["market"])
        closes = [r[3] for r in kl] if kl else []
        highs = [r[1] for r in kl] if kl else []      # r=(open,high,low,close,volume)
        lows = [r[2] for r in kl] if kl else []
        opens = [r[0] for r in kl] if kl else []
        d = {}
        if len(closes) >= 60:
            d["expma12"] = ema(closes[-30:], 12)
            d["expma50"] = ema(closes[-60:], 50)
            d["ma5"] = sum(closes[-5:]) / 5
            d["ma10"] = sum(closes[-10:]) / 10
            d["ma20"] = sum(closes[-20:]) / 20
            d["sup10"] = min(lows[-10:])
            d["res10"] = max(highs[-10:])
            d["hi60"] = max(highs[-60:])
            d["lo60"] = min(lows[-60:])
            prev_hi = max(highs[-20:-10]); recent_hi = max(highs[-10:])
            prev_lo = min(lows[-20:-10])
            bc = 0
            if q["price"] < prev_lo: bc += 1
            if recent_hi < prev_hi: bc += 1
            if q["price"] < d["ma20"] and d["ma5"] < d["ma10"]: bc += 1
            d["bear_confirm"] = bc
        mv = q["price"] * p["shares"]
        cost_mv = p["cost"] * p["shares"]
        pl = mv - cost_mv
        pl_pct = pl / cost_mv * 100 if cost_mv else 0
        day_pl = (q["price"] - q["pre_close"]) * p["shares"] if q["pre_close"] else 0
        rng = (q["high"] - q["low"]) or 1
        pos_in_range = (q["price"] - q["low"]) / rng * 100
        avg = (q["amt_wan"] * 1e4) / (q["vol_hand"] * 100) if q["vol_hand"] else None
        lp = limit_pct(p["code"], p["name"])
        up_limit = round(q["pre_close"] * (1 + lp / 100), 2)
        dn_limit = round(q["pre_close"] * (1 - lp / 100), 2)
        tstr = q["time"] or ""
        hhmmss = int(tstr[8:14]) if len(tstr) >= 14 and tstr[8:14].isdigit() else 0
        closed = hhmmss >= 150500
        vr = q["vol_ratio"]
        vr_valid = (vr is not None) and (0 < vr < 60) and not closed
        fu = funds.get(p["code"])
        alerts = []
        if abs(q["chg_pct"] or 0) >= 3:
            alerts.append("涨跌幅%.2f%%≥3%%" % q["chg_pct"])
        if vr_valid and vr >= 2:
            alerts.append("量比%.2f≥2放量" % vr)
        if abs(q["price"] - p["cost"]) / p["cost"] * 100 <= 2:
            alerts.append("逼近成本线(差%.1f%%)" % abs(q["price"] - p["cost"]) / p["cost"] * 100)
        if up_limit and q["price"] >= up_limit * 0.97:
            alerts.append("临近涨停(%.2f)" % up_limit)
        if dn_limit and q["price"] <= dn_limit * 1.03:
            alerts.append("临近跌停(%.2f)" % dn_limit)

        # ===== 模块一：分时做T指导（当日分时数据）=====
        if closed:
            tac_t = ("已收盘：今日低%.2f→高%.2f，收于日内位置%.0f%%，均价%.2f。"
                     "明日以今日低点%.2f为分时防守位，跌破不接；放量过今日高点%.2f再考虑跟进。"
                     % (q["low"], q["high"], pos_in_range, avg or 0, q["low"], q["high"]))
        elif vr_valid and vr >= 2 and pos_in_range >= 85:
            tac_t = ("高位放量（日内位置%.0f%%/量比%.2f）：均价%.2f上方的冲高都是做T高抛区，"
                     "抛出后等回落至均价%.2f附近缩量再接回。"
                     % (pos_in_range, vr, avg or 0, avg or 0))
        elif vr_valid and vr < 1 and pos_in_range <= 20:
            tac_t = ("低位缩量（日内位置%.0f%%/量比%.2f）：贴近分时低点%.2f可试低吸做T，"
                     "买入后反弹至均价%.2f上方即T出，不恋战。"
                     % (pos_in_range, vr, q["low"], avg or 0))
        elif avg and q["price"] < avg and (q["chg_pct"] or 0) < -2:
            tac_t = ("跌破当日均价%.2f且走弱：分时弱势，今日放弃做T，持币观望等明日。" % (avg or 0))
        else:
            tac_t = ("分时无显著信号（日内位置%.0f%%）：按兵不动，14:55后按当日位置决定去留。"
                     % pos_in_range)

        # ===== 模块二：日线波段指导（日线数据）=====
        if d:
            wave = ("支撑：EXPMA12 %.2f / 近10日低点%.2f / EXPMA50 %.2f；"
                    "压力：近10日高点%.2f / 60日高点%.2f。"
                    % (d["expma12"], d["sup10"], d["expma50"], d["res10"], d["hi60"]))
            if q["price"] < d["expma50"]:
                wave += "价格在EXPMA50下方，波段弱势，反弹至EXPMA12附近（%.2f）先减后看。" % d["expma12"]
            elif d["bear_confirm"] >= 2:
                wave += ("123法则出现%d项下跌确认：反弹不追，守EXPMA12（%.2f），破位止损。"
                         % (d["bear_confirm"], d["expma12"]))
            elif q["price"] > d["expma12"] > d["expma50"]:
                wave += ("EXPMA多头排列：波段持股，回踩EXPMA12（%.2f）不破可加，"
                         "跌破EXPMA50（%.2f）波段离场。" % (d["expma12"], d["expma50"]))
            else:
                wave += "趋势中性：EXPMA12（%.2f）附近震荡对待，突破跟进、破位退。" % d["expma12"]
        else:
            wave = "日线数据暂缺，波段指导待数据恢复后自动生成。"

        # ===== 模块三：超短交易纪律（固定条款+个性化数字）=====
        disc = ("① 持仓周期：买入起5个交易日内必须决断，最长15日（波段）；"
                "② 止损：买入价-5%%（本票现价对应%.2f），触发无条件执行；"
                "③ 止盈：+8%%减半（现价对应%.2f），剩余仓位看EXPMA12（%.2f）去留；"
                "④ 禁止：不在候选池外的股票冲动买入，计划外操作必须登记原因。"
                % (round(q["price"] * 0.95, 2), round(q["price"] * 1.08, 2),
                   d.get("expma12", q["price"])))

        # ===== 模块四：盘后作战指令（明日/未来几日：走/留判断）=====
        if d:
            stop_px = round(min(p["cost"], q["price"]) * 0.95, 2)  # 当前有效止损位
            px_stop = round(q["price"] * 0.95, 2)
            if q["price"] <= p["cost"] * 0.95:
                # 深套：成本止损线已跌穿，止损纪律已无可执行性，诚实重构指令
                oh = ("【减仓】浮亏%.1f%%深套，成本止损线%.2f早已跌穿：明日反弹至EXPMA12（%.2f）"
                      "附近坚决减仓降低敞口；若经你决策继续持有，以现价为基准重设止损%.2f（-5%%），"
                      "跌破无条件清仓，不许再扛。"
                      % (pl_pct, round(p["cost"] * 0.95, 2), d["expma12"], px_stop))
            elif pl_pct <= -8:
                oh = ("【减仓】浮亏%.1f%%已逼近止损线（%.2f）：明日反弹至EXPMA12（%.2f）附近减仓，"
                      "跌破%.2f无条件清仓，不扛。" % (pl_pct, stop_px, d["expma12"], stop_px))
            elif pl_pct >= 8:
                oh = ("【走/减】浮盈%.1f%%已达第一目标：明日冲高清半仓锁定，剩余半仓看EXPMA12（%.2f），"
                      "跌破全清。" % (pl_pct, d["expma12"]))
            elif q["price"] > d["expma12"] > d["expma50"] and d["bear_confirm"] == 0:
                oh = ("【留/持】EXPMA多头排列且123法则无下跌确认：继续持有；回踩EXPMA12（%.2f）"
                      "不破可低吸加仓，跌破EXPMA50（%.2f）再离场。" % (d["expma12"], d["expma50"]))
            elif d["bear_confirm"] >= 2:
                oh = ("【走】123法则出现%d项下跌确认、趋势转弱：明日反弹至EXPMA12（%.2f）附近离场，"
                      "不恋战，持币等下一个候选池信号。" % (d["bear_confirm"], d["expma12"]))
            elif q["price"] < d["expma50"]:
                oh = ("【观察】价格位于EXPMA50（%.2f）下方、波段弱势：明日反弹至EXPMA12（%.2f）先减后看，"
                      "重新站上EXPMA50再议持有。" % (d["expma50"], d["expma12"]))
            else:
                oh = ("【观察】趋势中性：守EXPMA12（%.2f），跌破减仓；放量突破近10日高点%.2f可加仓。"
                      % (d["expma12"], d["res10"]))
        else:
            oh = "日线数据暂缺，盘后作战指令待数据恢复后自动生成。"

        rows.append({
            "code": p["code"], "name": p["name"], "cost": p["cost"],
            "shares": p["shares"], "price": q["price"],
            "chg_pct": q["chg_pct"] or 0, "high": q["high"], "low": q["low"],
            "avg": avg, "pre_close": q["pre_close"], "time": q["time"],
            "vol_ratio": vr if vr_valid else None, "turnover": q["turnover"] or 0,
            "amt_wan": q["amt_wan"] or 0, "mv": mv, "cost_mv": cost_mv,
            "pl": pl, "pl_pct": pl_pct, "day_pl": day_pl,
            "pos_in_range": pos_in_range, "up_limit": up_limit, "dn_limit": dn_limit,
            "limit_pct": lp, "closed": closed,
            "fund_date": fu["trade_date"] if fu else None,
            "fund_main": fu["main_net"] if fu else None,
            "alerts": alerts, "tac_t": tac_t, "wave": wave, "disc": disc,
            "order": oh,
            # ===== v3.0 新增：日线因子与派生指标（关键价位色块条/回测区复用）=====
            "expma12": d.get("expma12"), "expma50": d.get("expma50"),
            "ma5": d.get("ma5"), "ma10": d.get("ma10"), "ma20": d.get("ma20"),
            "sup10": d.get("sup10"), "res10": d.get("res10"),
            "hi60": d.get("hi60"), "lo60": d.get("lo60"),
            "bear_confirm": d.get("bear_confirm", 0),
            "amp_today": ((q["high"] - q["low"]) / q["pre_close"] * 100) if q["pre_close"] else 0,
            "amp20": (sum((highs[i] - lows[i]) / max(closes[i], 1e-9)
                          for i in range(len(closes) - 20, len(closes))) / 20 * 100)
                     if len(closes) >= 20 else None,
            "stop_px": round(min(p["cost"], q["price"]) * 0.95, 2),
            "stop_basis": ("现价基准·成本止损已穿" if q["price"] <= p["cost"] * 0.95
                           else "成本基准-5%"),
            "tgt_px": round(p["cost"] * 1.08, 2),
        })
        time.sleep(0.3)
    return rows


def render(rows=None):
    """v3.0 起：版面设计委托 render_v3.render()（分类排版+色块+回测战绩区）。
    pos_watch 只负责数据采集与策略文本生成，版面由 render_v3 统一维护。"""
    if rows is None:
        rows = build_rows()
    import render_v3
    return render_v3.render(rows)


if __name__ == "__main__":
    rows = build_rows()
    for r in rows:
        print("%-6s %-7s 现价%8.2f %+6.2f%% | %s股 | 盈亏%+10.2f万(%+6.2f%%)"
              % (r["code"], r["name"], r["price"], r["chg_pct"],
                 "{:,}".format(r["shares"]), r["pl"] / 1e4, r["pl_pct"]))
    pl = render(rows)
    print("组合总盈亏: %+.2f万 | v3.0 页面已生成" % (pl / 1e4))
