#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同花顺资金流展示页生成器：读取 flows.jsonl -> 生成自包含 dashboard.html
- 单文件、无外部 CDN、可离线打开
- 配色遵循国内惯例：红=净流入(涨)，绿=净流出(跌)
用法: python3 render_dashboard.py
"""
import html
import sys
from datetime import datetime

sys.path.insert(0, "/workspace/ths_daily")
import ths_common as C

OUT = C.DIR / "dashboard.html"


def wan(v):
    """元 -> 万元，保留2位"""
    return "%.2f" % ((v or 0) / 1e4)


def cls(v):
    return "up" if (v or 0) > 0 else ("down" if (v or 0) < 0 else "flat")


def render():
    best = C.ledger_records()
    by_code = {}
    for (code, _d), r in best.items():
        by_code.setdefault(code, []).append(r)
    for code in by_code:
        by_code[code].sort(key=lambda r: r["trade_date"])

    gen_at = datetime.now(C.CST).strftime("%F %T")
    all_dates = sorted({d for (_c, d) in best})
    rng = ("%s ~ %s" % (all_dates[0], all_dates[-1])) if all_dates else "暂无数据"

    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>同花顺口径资金流看板</title>
<style>
  :root { --red:#d93026; --green:#0e9f6e; --ink:#1f2933; --sub:#6b7280;
          --line:#e5e7eb; --bg:#f7f8fa; --card:#ffffff; }
  * { box-sizing: border-box; }
  body { margin:0; padding:24px; background:var(--bg); color:var(--ink);
         font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
  .wrap { max-width:1080px; margin:0 auto; }
  h1 { font-size:22px; margin:0 0 4px; }
  .meta { color:var(--sub); font-size:13px; margin-bottom:20px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
           gap:12px; margin-bottom:24px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:14px 16px; }
  .card .nm { font-size:14px; font-weight:600; }
  .card .cd { font-size:12px; color:var(--sub); }
  .card .v { font-size:24px; font-weight:700; margin-top:6px; }
  .card .d { font-size:12px; color:var(--sub); margin-top:2px; }
  .up { color:var(--red); } .down { color:var(--green); } .flat { color:var(--sub); }
  section { background:var(--card); border:1px solid var(--line);
            border-radius:12px; padding:16px 18px; margin-bottom:16px; }
  h2 { font-size:16px; margin:0 0 10px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { padding:7px 8px; text-align:right; border-bottom:1px solid var(--line);
           white-space:nowrap; }
  th { color:var(--sub); font-weight:500; font-size:12px; }
  td:first-child, th:first-child { text-align:left; }
  tr:last-child td { border-bottom:none; }
  .tot td { font-weight:700; background:#fafafa; }
  .note { color:var(--sub); font-size:12px; margin-top:10px; line-height:1.7; }
  .scroll { overflow-x:auto; }
</style>
</head>
<body><div class="wrap">
<h1>同花顺口径 · 资金流看板</h1>
<div class="meta">生成时间：__GEN__ ｜ 数据范围：__RNG__ ｜ 本页每5分钟自动刷新 ｜ 主力净流入 = 超大单净 + 大单净（同花顺个股页口径）</div>
""".replace("__GEN__", gen_at).replace("__RNG__", rng))

    # 总览卡片：最近5个交易日主力净额合计
    cards = ['<div class="cards">']
    for code, mid, name in C.STOCKS:
        rows = by_code.get(code, [])
        last5 = rows[-5:]
        tot = sum(r["main_net"] or 0 for r in last5)
        latest = rows[-1]["trade_date"] if rows else "-"
        cards.append(
            '<div class="card"><div class="nm">%s</div><div class="cd">%s · 截至 %s</div>'
            '<div class="v %s">%s万</div><div class="d">近5日主力净额合计</div></div>'
            % (html.escape(name), code, latest, cls(tot), wan(tot)))
    cards.append("</div>")
    parts.append("".join(cards))

    # 每股票明细
    for code, mid, name in C.STOCKS:
        rows = by_code.get(code, [])
        parts.append("<section><h2>%s（%s）逐日资金流</h2>" % (html.escape(name), code))
        if not rows:
            parts.append('<div class="note">暂无数据</div></section>')
            continue
        parts.append('<div class="scroll"><table><tr><th>交易日</th><th>收盘</th>'
                     "<th>成交量(万手)</th><th>成交额(亿)</th><th>超大单净(万)</th>"
                     "<th>大单净(万)</th><th>中单净(万)</th><th>小单净(万)</th>"
                     "<th>主力净额(万)</th></tr>")
        tm = tv = ta = 0.0
        for r in rows:
            m = r["main_net"] or 0
            tm += m
            tv += (r.get("vol_gu") or 0) / 1e6
            ta += (r.get("amt_yuan") or 0) / 1e8
            vol = (r.get("vol_gu") or 0) / 1e6
            amt = (r.get("amt_yuan") or 0) / 1e8
            close = r.get("close")
            parts.append(
                "<tr><td>%s</td><td>%s</td><td>%.2f</td><td>%.2f</td>"
                '<td class="%s">%s</td><td class="%s">%s</td>'
                '<td class="%s">%s</td><td class="%s">%s</td>'
                '<td class="%s"><b>%s</b></td></tr>'
                % (r["trade_date"],
                   ("%.2f" % close) if close is not None else "-",
                   vol, amt,
                   cls(r.get("mass_net")), wan(r.get("mass_net")),
                   cls(r.get("big_net")), wan(r.get("big_net")),
                   cls(r.get("medium_net")), wan(r.get("medium_net")),
                   cls(r.get("small_net")), wan(r.get("small_net")),
                   cls(m), wan(m)))
        parts.append('<tr class="tot"><td>合计</td><td>-</td><td>%.2f</td><td>%.2f</td>'
                     '<td colspan="4"></td><td class="%s">%s</td></tr>'
                     % (tv, ta, cls(tm), wan(tm)))
        parts.append("</table></div>")
        parts.append('<div class="note">采集时间戳：%s ｜ 交易日来源：%s</div></section>'
                     % (rows[-1].get("collected_at", "-"), rows[-1].get("date_source", "-")))

    parts.append("""
<section><h2>说明</h2><div class="note">
1. 数据采自同花顺官方接口（个股页资金快照 + 日K线），非估算值；主力净流入 = 超大单净额 + 大单净额。<br>
2. 颜色遵循国内惯例：<span class="up">红色 = 净流入</span>，<span class="green down">绿色 = 净流出</span>。<br>
3. 账本文件：/workspace/ths_daily/flows.jsonl（每股票每交易日一行，同日多行以最后一行为准）。<br>
4. 采集由云端定时任务自动完成（每个交易日 北京 08:30 / 15:45 / 18:00 三次），无需打开 WorkBuddy；本页托管于 GitHub Pages，每5分钟自动刷新，始终展示最新数据。
</div></section>
</div></body></html>""")

    OUT.write_text("".join(parts), encoding="utf-8")
    # 同时输出 index.html 供 GitHub Pages 作为站点首页（默认文档名）
    idx = C.DIR / "index.html"
    idx.write_text("".join(parts), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    p = render()
    print("已生成:", p)
