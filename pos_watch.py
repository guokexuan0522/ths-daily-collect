# -*- coding: utf-8 -*-
"""持仓盯盘引擎 M1：实时行情拉取(腾讯) + 盈亏/异动计算 + 自包含盯盘页渲染。

红涨绿跌（A股看盘习惯）。输出 position.html(本地) 与 index.html(Pages首页)。
铁律#3：页面每个数字都可追溯到来源字段；无依据不出结论。
"""
import json
import time
import urllib.request
from pathlib import Path

DIR = Path(__file__).resolve().parent
POS_FILE = DIR / "positions.json"
LEDGER = DIR / "flows.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://gu.qq.com/"}


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_quotes(markets_codes):
    """批量拉腾讯实时行情。返回 {code: dict}"""
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
            "name": f[1], "code": f[2],
            "price": num(3), "pre_close": num(4), "open": num(5),
            "vol_hand": num(6), "time": f[30] if len(f) > 30 else "",
            "chg": num(31), "chg_pct": num(32),
            "high": num(33), "low": num(34),
            "amt_wan": num(37), "turnover": num(38),
            "vol_ratio": (num(50) or 0) / 100.0 if num(50) else None,
            "circ_mv": num(45), "total_mv": num(46), "pb": num(47),
        }
    return out


def limit_pct(code, name):
    """涨跌停幅度：ST 5%；创业板(30x)/科创板(688) 20%；其余 10%"""
    if "ST" in name.upper():
        return 5.0
    if code.startswith("30") or code.startswith("688"):
        return 20.0
    return 10.0


def latest_fund_flows():
    """flows.jsonl -> {code: 最新交易日主力净额记录}"""
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
    if v is None:
        return "-"
    return "{:+,.2f}万".format(v / 1e4)


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
        # 收盘判定：腾讯时间戳 HHMMSS >= 150500 视为已收盘（盘后量比字段不可信）
        tstr = (q["time"] or "")
        hhmmss = int(tstr[8:14]) if len(tstr) >= 14 and tstr[8:14].isdigit() else 0
        closed = hhmmss >= 150500
        vr = q["vol_ratio"]
        vr_valid = (vr is not None) and (0 < vr < 60) and not closed
        fu = funds.get(p["code"])
        alerts, tac = [], None

        # 异动规则（全部带数值依据；盘后不计量比类异动——收盘后该字段失真）
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

        # 做T简化预案（条件式，铁律#3）；收盘后切换复盘口径
        if closed:
            tac = ("已收盘：今日振幅%.1f%%（低%.2f→高%.2f），收于日内位置%.0f%%，"
                   "做好明日预案即可，不盘后冲动决策" % (
                       (q["high"] - q["low"]) / q["pre_close"] * 100 if q["pre_close"] else 0,
                       q["low"], q["high"], pos_in_range))
        elif pl_pct >= 3 and pos_in_range >= 85 and vr_valid and vr >= 1.5:
            tac = ("高位放量(日内位置%.0f%%/量比%.2f)，浮盈%.1f%%，可考虑冲高抛出一部分做T"
                   % (pos_in_range, vr, pl_pct))
        elif pos_in_range <= 15 and vr_valid and vr < 1 and pl_pct > -8:
            tac = ("低位缩量(日内位置%.0f%%/量比%.2f)，若继续缩量下探可关注低吸做T"
                   % (pos_in_range, vr))
        elif q["price"] < (avg or q["price"]) and (q["chg_pct"] or 0) < -2:
            tac = "跌破当日均价%.2f且走弱，观望，放弃今日做T" % (avg or 0)
        elif up_limit and q["price"] >= up_limit * 0.97:
            tac = "涨停附近，不追高，持仓者视封单决定去留"
        else:
            tac = "按兵不动，尾盘14:55后按当日走势决定去留"

        rows.append({
            "code": p["code"], "name": p["name"], "cost": p["cost"],
            "shares": p["shares"], "since": p["since"],
            "price": q["price"], "chg_pct": q["chg_pct"] or 0,
            "high": q["high"], "low": q["low"], "avg": avg,
            "pre_close": q["pre_close"], "time": q["time"],
            "vol_ratio": vr if vr_valid else None, "turnover": q["turnover"],
            "amt_wan": q["amt_wan"], "mv": mv, "cost_mv": cost_mv,
            "pl": pl, "pl_pct": pl_pct, "day_pl": day_pl,
            "pos_in_range": pos_in_range, "up_limit": up_limit, "dn_limit": dn_limit,
            "limit_pct": lp, "closed": closed,
            "fund_date": fu["trade_date"] if fu else None,
            "fund_main": fu["main_net"] if fu else None,
            "alerts": alerts, "tac": tac,
        })
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
        color = "#d63031" if up else "#00b894"      # 红涨绿跌
        plcolor = "#d63031" if plup else "#00b894"
        fund_txt = fmt_wan(r["fund_main"]) if r["fund_main"] is not None else "暂无"
        fund_color = "#d63031" if (r["fund_main"] or 0) >= 0 else "#00b894"
        alert_html = "".join('<span class="tag">⚠ %s</span>' % a for a in r["alerts"])
        posbar = min(max(r["pos_in_range"], 0), 100)
        cards.append("""
<div class="card%s">
  <div class="chead">
    <span class="nm">%s <small>%s</small></span>
    <span class="px" style="color:%s">%.2f</span>
    <span class="chg" style="color:%s">%+.2f%%</span>
    %s
  </div>
  <div class="grid">
    <div><label>持仓盈亏</label><b style="color:%s">%s (%.2f%%)</b></div>
    <div><label>当日盈亏</label><b style="color:%s">%s</b></div>
    <div><label>成本线</label><b>%.3f（现价距成本 %+.1f%%）</b></div>
    <div><label>今日高/低</label><b>%.2f / %.2f（涨跌停 ±%.0f%%）</b></div>
    <div><label>当日均价</label><b>%s</b></div>
    <div><label>量比/换手</label><b>%s / %.2f%%</b></div>
  </div>
  <div class="range"><div class="rangefill" style="width:%.0f%%"></div><div class="rangelabel">日内位置 %.0f%%（低%.2f → 高%.2f）</div></div>
  <div class="fund">%s 主力净额：<b style="color:%s">%s</b> ｜ 成交额 %s万</div>
  <div class="tac"><b>做T预案：</b>%s</div>
  <div class="alerts">%s</div>
</div>""" % (
            " alert" if r["alerts"] else "",
            r["name"], r["code"], color, r["price"], color, r["chg_pct"],
            ("<span class='cls'>已收盘</span>" if r["closed"] else ""),
            plcolor, fmt_wan(r["pl"]), r["pl_pct"],
            color, fmt_wan(r["day_pl"]),
            r["cost"], (r["price"] - r["cost"]) / r["cost"] * 100,
            r["high"], r["low"], r["limit_pct"],
            ("%.2f" % r["avg"]) if r["avg"] else "-",
            ("%.2f" % r["vol_ratio"]) if r["vol_ratio"] else "-", r["turnover"] or 0,
            posbar, r["pos_in_range"], r["low"], r["high"],
            r["fund_date"] or "-", fund_color, fund_txt,
            "{:,.0f}".format(r["amt_wan"] or 0),
            r["tac"], alert_html))

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>持仓作战页 · 实时盯盘</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#2d3436;padding:14px}
.hd{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:12px}
h1{font-size:20px}.hd .meta{font-size:12px;color:#636e72}
a{color:#0984e3;text-decoration:none}
.ov{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.ov .box{background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.ov label{font-size:12px;color:#636e72;display:block;margin-bottom:4px}
.ov b{font-size:20px}
.card{background:#fff;border-radius:12px;padding:14px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.07)}
.card.alert{border:2px solid #e17055}
.chead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.nm{font-size:17px;font-weight:700}
.px{font-size:30px;font-weight:800}
.chg{font-size:16px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-bottom:10px}
.grid label{font-size:12px;color:#636e72;display:block}
.grid b{font-size:14px;font-weight:600}
.range{position:relative;height:22px;background:#dfe6e9;border-radius:11px;margin:8px 0;overflow:hidden}
.rangefill{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,#00b89433,#d6303133)}
.rangelabel{position:absolute;width:100%;text-align:center;font-size:12px;line-height:22px;color:#2d3436}
.fund{font-size:13px;margin:6px 0;color:#636e72}
.tac{font-size:14px;background:#f1f2f6;border-left:4px solid #0984e3;padding:8px 10px;border-radius:0 8px 8px 0;margin:6px 0}
.alerts{margin-top:6px}
.cls{display:inline-block;background:#dfe6e9;color:#636e72;font-size:11px;padding:2px 8px;border-radius:10px}
.tag{display:inline-block;background:#ffeaa7;color:#d63031;font-size:12px;padding:2px 8px;border-radius:10px;margin:2px 4px 2px 0}
.ft{font-size:12px;color:#b2bec3;margin-top:14px;line-height:1.7}
</style>
</head>
<body>
<div class="hd">
  <h1>持仓作战页 <a href="flows.html">→ 资金流看板</a></h1>
  <div class="meta">生成 __GEN__ ｜ 每60秒自动刷新 ｜ 红=涨/盈利 绿=跌/亏损</div>
</div>
<div class="ov">
  <div class="box"><label>总市值</label><b>__TOTMV__ 万</b></div>
  <div class="box"><label>持仓总盈亏</label><b style="color:__TOTPLC__">__TOTPL__ 万 (__TOTPLPCT__%%)</b></div>
  <div class="box"><label>当日盈亏</label><b style="color:__TOTDAYC__">__TOTDAY__ 万</b></div>
  <div class="box"><label>持仓数</label><b>__N__ 只</b></div>
</div>
__CARDS__
<div class="ft">
 数据来源：腾讯实时行情（分钟级快照）；主力净额为同花顺口径（超大单+大单），取自资金流账本最近交易日。<br>
  做T预案为条件式参考（触发条件+依据均已列出），非买卖指令；执行与否由你决定。本页每60秒自动刷新。
</div>
</body>
</html>"""
    html = (html.replace("__GEN__", gen)
            .replace("__TOTMV__", "{:,.2f}".format(tot_mv / 1e4))
            .replace("__TOTPLC__", "#d63031" if tot_pl >= 0 else "#00b894")
            .replace("__TOTPL__", "{:+,.2f}".format(tot_pl / 1e4))
            .replace("__TOTPLPCT__", "%+.2f" % tot_pl_pct)
            .replace("__TOTDAYC__", "#d63031" if tot_day >= 0 else "#00b894")
            .replace("__TOTDAY__", "{:+,.2f}".format(tot_day / 1e4))
            .replace("__N__", str(len(rows)))
            .replace("__CARDS__", "".join(cards)))
    (DIR / "position.html").write_text(html, encoding="utf-8")
    (DIR / "index.html").write_text(html, encoding="utf-8")
    return tot_pl


if __name__ == "__main__":
    rows = build_rows()
    for r in rows:
        print("%-6s %-7s 现价%8.2f %+6.2f%% | 盈亏%+10.2f万(%+6.2f%%) | 量比%s | %s"
              % (r["code"], r["name"], r["price"], r["chg_pct"],
                 r["pl"] / 1e4, r["pl_pct"],
                 ("%.2f" % r["vol_ratio"]) if r["vol_ratio"] else "-",
                 "；".join(r["alerts"]) or "无异动"))
    pl = render(rows)
    print("组合总盈亏: %+.2f万 | position.html/index.html 已生成" % (pl / 1e4))
