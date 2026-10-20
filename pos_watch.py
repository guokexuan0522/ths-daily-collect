# -*- coding: utf-8 -*-
"""持仓作战平台 v2.0 渲染器：实时盯盘 + 三模块策略指南 + 选股候选池。

红涨绿跌（A股看盘习惯）。输出 position.html(本地) 与 index.html(Pages首页)。
三模块策略指南（命名规范化，v2.0 起）：
  「分时做T指导」— 基于当日分时数据（均价/日内位置/量比）
  「日线波段指导」— 基于日线数据（EXPMA/均线/支撑压力/123法则）
  「超短交易纪律」— 固定纪律条款，个性化数字
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
VERSION = "v2.0"

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
        highs = [r[2] for r in kl] if kl else []
        lows = [r[3] for r in kl] if kl else []
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
        })
        time.sleep(0.3)
    return rows


def render(rows=None):
    if rows is None:
        rows = build_rows()
    tot_mv = sum(r["mv"] for r in rows)
    tot_cost = sum(r["cost_mv"] for r in rows)
    tot_pl = tot_mv - tot_cost
    tot_pl_pct = tot_pl / tot_cost * 100 if tot_cost else 0
    tot_day = sum(r["day_pl"] for r in rows)
    gen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    cards = []
    for r in rows:
        up = r["chg_pct"] >= 0
        plup = r["pl_pct"] >= 0
        color = "#d63031" if up else "#00b894"
        plcolor = "#d63031" if plup else "#00b894"
        fund_color = "#d63031" if (r["fund_main"] or 0) >= 0 else "#00b894"
        alert_html = "".join('<span class="tag">⚠ %s</span>' % a for a in r["alerts"])
        posbar = min(max(r["pos_in_range"], 0), 100)
        cards.append("""
<div class="card%s">
  <div class="chead">
    <span class="nm">%s <small>%s</small></span>
    <span class="px" style="color:%s">%.2f</span>
    <span class="chg" style="color:%s">%+.2f%%</span>
    <span class="cls">%s</span>
  </div>
  <div class="grid">
    <div><label>持仓数量</label><b>%s 股</b></div>
    <div><label>成本价 / 市值</label><b>%.3f ｜ %s万</b></div>
    <div><label>持仓盈亏</label><b style="color:%s">%s (%.2f%%)</b></div>
    <div><label>当日盈亏</label><b style="color:%s">%s</b></div>
    <div><label>今日高/低</label><b>%.2f / %.2f（涨跌停±%.0f%%：%.2f/%.2f）</b></div>
    <div><label>量比 / 换手</label><b>%s ｜ %.2f%%</b></div>
  </div>
  <div class="range"><div class="rangefill" style="width:%.0f%%"></div><div class="rangelabel">日内位置 %.0f%%（低%.2f → 高%.2f，均价%s）</div></div>
  <div class="fund">%s 主力净额：<b style="color:%s">%s</b> ｜ 当日成交额 %s万</div>
  <div class="alerts">%s</div>
  <div class="mod"><b>分时做T指导</b>%s</div>
  <div class="mod"><b>日线波段指导</b>%s</div>
  <div class="mod disc"><b>超短交易纪律</b>%s</div>
</div>""" % (
            " alert" if r["alerts"] else "",
            r["name"], r["code"], color, r["price"], color, r["chg_pct"],
            "已收盘" if r["closed"] else "交易中",
            "{:,}".format(r["shares"]), r["cost"], "{:,.2f}".format(r["mv"] / 1e4),
            plcolor, fmt_wan(r["pl"]), r["pl_pct"],
            color, fmt_wan(r["day_pl"]),
            r["high"], r["low"], r["limit_pct"], r["up_limit"], r["dn_limit"],
            ("%.2f" % r["vol_ratio"]) if r["vol_ratio"] else "盘后不显示", r["turnover"],
            posbar, r["pos_in_range"], r["low"], r["high"],
            ("%.2f" % r["avg"]) if r["avg"] else "-",
            r["fund_date"] or "-", fund_color,
            fmt_wan(r["fund_main"]) if r["fund_main"] is not None else "暂无",
            "{:,.0f}".format(r["amt_wan"]),
            alert_html or '<span class="tag ok">无异动</span>',
            r["tac_t"], r["wave"], r["disc"]))

    # ===== 选股候选池板块 =====
    pick_html = ('<div class="sec"><h2>每日选股 · 候选池 <small>'
                 '（M2引擎 · 全A海扫 · 数据源：新浪全市场+日K+同花顺资金流）</small></h2>')
    picks = None
    if PICKS_FILE.exists():
        try:
            picks = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            picks = None
    if not picks or not picks.get("picks"):
        pick_html += '<div class="mod">今日选股结果尚未生成（盘后15:45后自动运行，或手动触发）</div>'
    else:
        pick_html += ('<div class="pmeta">生成于 %s ｜ 扫描 %d 只 → 入池 %d → 打分 %d ｜ '
                      '耗时 %.0fs ｜ 候选 %d 只（★为主推）</div>'
                      % (picks["generated_at"], picks["market_scanned"],
                         picks["layer1_pool"], picks["layer2_scored"],
                         picks["elapsed_sec"], len(picks["picks"])))
        for p in picks["picks"]:
            tag = "★主推" if p["primary"] else "备选"
            reasons = "".join("<li>%s</li>" % x for x in p["reasons"])
            pick_html += """
<div class="pick">
  <div class="phead"><span class="pnm">#%d %s <small>%s</small></span>
    <span class="pscore">%s 得分 %.1f</span>
    <span class="pprice">现价 %.2f（%+.2f%%）成交额%.1f亿</span></div>
  <ul class="why">%s</ul>
  <div class="prow"><b>买入条件：</b>%s</div>
  <div class="prow"><b>止损位：</b>%s</div>
  <div class="prow"><b>目标位：</b>%s</div>
  <div class="prow"><b>失效条件：</b>%s</div>
</div>""" % (p["rank"], p["name"], p["code"], tag, p["score"],
            p["price"], p["chg"], p["amount_yi"], reasons,
            p["buy"], p["stop"], p["target"], p["invalid"])
    pick_html += '</div>'

    rev_html = "".join('<li><b>%s</b>（%s）：%s</li>' % r for r in REVISION_LOG)
    rules = ("①决策权在你，模型只给依据禁指令话术 ②诚实红线：亏就是亏禁报喜藏忧 "
             "③无依据不出票 ④先回测后模拟盘再实盘 ⑤每票预设数字止损触发即执行 "
             "⑥计划外交易必须登记 ⑦数据不许猜不许编 ⑧全部版本化留修订记录 "
             "⑨财联社任务线隔离不碰 ⑩中线≤2个自然月 ⑪仓位框架不盘中破 ⑫每周复盘闭环")

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>持仓作战平台 · 实时盯盘 + 每日选股</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#2d3436;padding:14px}
.hd{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:6px}
h1{font-size:20px}.hd .meta{font-size:12px;color:#636e72}
.badge{display:inline-block;background:#0984e3;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:12px;margin-left:8px;vertical-align:middle}
a{color:#0984e3;text-decoration:none}
.ov{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.ov .box{background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.ov label{font-size:12px;color:#636e72;display:block;margin-bottom:4px}
.ov b{font-size:20px}
.sec{background:#fff;border-radius:12px;padding:14px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.07)}
.sec h2{font-size:17px;margin-bottom:10px}.sec h2 small{font-size:12px;color:#636e72;font-weight:400}
.card{background:#fff;border-radius:12px;padding:14px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.07)}
.card.alert{border:2px solid #e17055}
.chead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.nm{font-size:17px;font-weight:700}
.px{font-size:30px;font-weight:800}
.chg{font-size:16px;font-weight:700}
.cls{background:#dfe6e9;color:#636e72;font-size:11px;padding:2px 8px;border-radius:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-bottom:10px}
.grid label{font-size:12px;color:#636e72;display:block}
.grid b{font-size:14px;font-weight:600}
.range{position:relative;height:22px;background:#dfe6e9;border-radius:11px;margin:8px 0;overflow:hidden}
.rangefill{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,#00b89433,#d6303133)}
.rangelabel{position:absolute;width:100%;text-align:center;font-size:12px;line-height:22px}
.fund{font-size:13px;margin:6px 0;color:#636e72}
.mod{font-size:13.5px;background:#f1f2f6;border-left:4px solid #0984e3;padding:8px 10px;border-radius:0 8px 8px 0;margin:6px 0;line-height:1.65}
.mod.disc{border-left-color:#e17055;background:#fdf2ec}
.alerts{margin-top:6px}
.tag{display:inline-block;background:#ffeaa7;color:#d63031;font-size:12px;padding:2px 8px;border-radius:10px;margin:2px 4px 2px 0}
.tag.ok{background:#dfe6e9;color:#636e72}
.pmeta{font-size:12px;color:#636e72;margin-bottom:8px}
.pick{border:1px solid #dfe6e9;border-radius:10px;padding:10px 12px;margin-bottom:10px}
.phead{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.pnm{font-size:15px;font-weight:700}
.pscore{color:#0984e3;font-weight:700;font-size:13px}
.pprice{font-size:12px;color:#636e72}
.why{margin:4px 0 6px 18px;font-size:13px;line-height:1.7}
.prow{font-size:13px;line-height:1.6;margin:2px 0}
.ft{background:#fff;border-radius:12px;padding:14px;margin:14px 0;font-size:12px;color:#636e72;line-height:1.8;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.ft h3{font-size:13px;color:#2d3436;margin-bottom:6px}
.ft ol{margin-left:18px}
</style>
</head>
<body>
<div class="hd">
  <h1>持仓作战平台<span class="badge">__VER__</span> <a href="flows.html">→ 资金流看板</a></h1>
  <div class="meta">生成 __GEN__ ｜ 每60秒自动刷新 ｜ 红=涨/盈利 绿=跌/亏损</div>
</div>
<div class="ov">
  <div class="box"><label>总市值</label><b>__TOTMV__ 万</b></div>
  <div class="box"><label>持仓总盈亏</label><b style="color:__TOTPLC__">__TOTPL__ 万 (__TOTPLPCT__%%)</b></div>
  <div class="box"><label>当日盈亏</label><b style="color:__TOTDAYC__">__TOTDAY__ 万</b></div>
  <div class="box"><label>持仓数</label><b>__N__ 只</b></div>
</div>
__CARDS__
__PICKS__
<div class="ft">
  <h3>修订记录</h3>
  <ol>__REV__</ol>
  <h3>铁律（项目宪法）</h3>
  <div>__RULES__</div>
  <h3>数据口径</h3>
  <div>实时行情：腾讯行情接口（分钟级快照，收盘后量比字段失真故盘后隐藏）；日线因子：新浪日K（EXPMA/均线/支撑压力/123法则）；主力净额：同花顺口径（超大单+大单），取自资金流账本最近交易日。选股引擎数据源：新浪全市场截面+新浪日K+同花顺资金流（东财接口当前403降级）。<br>
  本平台为信息与规则工具，非持牌投顾服务；所有操作由你决策，盈亏由你承担。策略指导均为条件式参考，触发条件与依据已在各模块列明。</div>
</div>
</body>
</html>"""
    html = (html.replace("__VER__", VERSION).replace("__GEN__", gen)
            .replace("__TOTMV__", "{:,.2f}".format(tot_mv / 1e4))
            .replace("__TOTPLC__", "#d63031" if tot_pl >= 0 else "#00b894")
            .replace("__TOTPL__", "{:+,.2f}".format(tot_pl / 1e4))
            .replace("__TOTPLPCT__", "%+.2f" % tot_pl_pct)
            .replace("__TOTDAYC__", "#d63031" if tot_day >= 0 else "#00b894")
            .replace("__TOTDAY__", "{:+,.2f}".format(tot_day / 1e4))
            .replace("__N__", str(len(rows)))
            .replace("__CARDS__", "".join(cards))
            .replace("__PICKS__", pick_html)
            .replace("__REV__", rev_html)
            .replace("__RULES__", rules))
    (DIR / "position.html").write_text(html, encoding="utf-8")
    (DIR / "index.html").write_text(html, encoding="utf-8")
    return tot_pl


if __name__ == "__main__":
    rows = build_rows()
    for r in rows:
        print("%-6s %-7s 现价%8.2f %+6.2f%% | %s股 | 盈亏%+10.2f万(%+6.2f%%)"
              % (r["code"], r["name"], r["price"], r["chg_pct"],
                 "{:,}".format(r["shares"]), r["pl"] / 1e4, r["pl_pct"]))
    pl = render(rows)
    print("组合总盈亏: %+.2f万 | v2.0 页面已生成" % (pl / 1e4))
