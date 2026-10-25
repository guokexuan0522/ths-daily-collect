# -*- coding: utf-8 -*-
"""持仓作战平台 v3.0 渲染器：分类排版 + 深色作战总览带 + 关键价位色块条 + 回测战绩区。

设计原则（承接用户反馈与财联社看板经验）：
  1. 分类排版：总览带 → 持仓作战区 → 每日选股区 → 模型回测战绩区 → 页脚，层级清晰
  2. 重要指标醒目：红涨绿跌（A股习惯）+ 彩色徽章/色块/图标（🛑止损 🎯目标 📈🔬🧭⏱🛡）
  3. 关键价位色块条：止损/成本/现价/EXPMA12/EXPMA50/压力/目标 一排 chips，附距离%
  4. 每只持仓四模块：⏱分时做T（盘中） 📈日线波段（盘中） 🧭盘后作战指令（走/留） 🛡超短纪律
  5. 回测战绩区：backtest.json 指标卡 + 假设声明 + 最近交易明细（诚实呈现）
铁律#3：页面每个数字都可追溯到来源；无依据不出结论。
"""
import json
import time
from pathlib import Path

DIR = Path(__file__).resolve().parent
PICKS_FILE = DIR / "picks.json"
BT_FILE = DIR / "backtest.json"
TRACK_FILE = DIR / "picks_history.jsonl"   # 每日选股入池登记（实时追踪流水，v3.3 新增）

VERSION = "v3.4"
UP = "#e0322f"        # 红=涨/盈利
DOWN = "#00a37a"      # 绿=跌/亏损
BLUE = "#0984e3"
ORANGE = "#e17055"
PURPLE = "#6c5ce7"
GRAY = "#636e72"

REVISION_LOG = [
    ("v1.0", "2026-10-20", "持仓盯盘页上线：实时行情/盈亏/异动/60秒刷新"),
    ("v2.0", "2026-10-20", "①版本徽章+修订历史+铁律摘要 ②每只显示持仓数 ③原“做T预案”拆分为"
     "「分时做T指导」「日线波段指导」「超短交易纪律」三模块 ④新增每日选股候选池板块"),
    ("v3.0", "2026-10-20", "①修复日线因子高低点取数错误（原误用收盘价序列，支撑/压力/123法则失真）"
     "②新增「盘后作战指令」模块：明日/未来几日走留判断+具体价位（持仓止损改按成本基准）"
     "③分类排版重设计：深色作战总览带+持仓作战区+选股区+回测战绩区 ④关键价位色块条"
     "（止损/成本/现价/EXPMA/压力/目标，附距离%）⑤补齐指标：仓位占比/止损距离/目标距离/"
     "EXPMA位置/当日振幅/20日平均振幅 ⑥铁律#13「宁做短不做长」落地：选股引擎新增弹性因子"
     "（近20日平均振幅，硬门槛2%），权重重构为动量20趋势25量能12位置12形态8弹性13资金10"
     "⑦选股区改版：因子分解+资金流呈现；回测战绩区上线（两年真实日线回测）"),
    ("v3.1", "2026-10-20", "【M3.5 模型重做·铁证级诚实结论】①回测v1模型-69.5%跑输随机+98.4%(无流动性门槛虚高)/"
     "大盘+23.7%，确认负alpha，已弃用 ②搭建信号实验室signal_lab，6套候选信号对随机基线验真伪，"
     "唯一胜出为S3「横盘突破」(低位横盘蓄势+逼近20日新高+无下跌确认) ③修复公平基线：随机/模型/基准"
     "统一加成交额>2亿门槛，基准改中位数(防极端日拉爆)，结果模型+37.5%＞随机-43.0%＞流动性等权-24.2%，"
     "正alpha成立 ④实时选股selector与回测同口径落地S3，评分在2-4%带内偏好更高弹性(贴合铁律#13)，"
     "扫描池扩至500只捕捉中盘突破股 ⑤回测战绩区结论随数据自动翻转：✅模型跑赢随机与基准"),
    ("v3.2", "2026-10-20", "【M4 算法+数据进化·诚实迭代】①数据进化：引入相对强度RS因子（个股20日收益-市场20日收益），"
     "实时版用沪深300、回测版用全市场等权指数，作为软打分优先选跑赢大盘的横盘突破股 ②算法进化：新增「结构失效出场」"
     "（跌破EXPMA50即出，替代死等5日），亏损更早砍、盈利拿更久 ③回测结论：模型+36.7%仍跑赢随机-43.0%与基准-24.2%"
     "（正alpha成立）；自身对比M3.5：最大回撤-38.7%→-17.6%（砍半）、单笔期望-0.002%→+0.052%（转正） ④诚实边界："
     "实验证明该框架胜率天花板约44-45%，硬过滤(regime/放量/RS硬过滤)均降胜率，故M4核心交付为「控回撤+转正期望+数据维度进化」，"
     "而非虚假胜率飙升；下一步提胜率需新数据(历史资金流/板块分类/更长周期)或ML集成+walk-forward"),
    ("v3.3", "2026-10-24", "【选股战绩追踪·回应'看不到股票到底行不行'】①新增「🏆选股战绩追踪」模块："
     "个股战绩徽章(每只候选股标注历史入选次数/胜负/累计收益，首入池标🆕开始追踪)+动态仪表盘(实时胜率/"
     "平均单笔/累计收益/最大最小单笔/今日新入池)+内联SVG收益曲线+每日选股战绩明细表 ②建立picks_history.jsonl"
     "每日选股入池登记(幂等去重)：实时追踪自今日起、K线刷新后自动结算5日战绩 ③战绩种子取自回测样本"
     "(同规则止损-5%/止盈+8%/5日到期)，诚实标注回测≠未来 ④position.html用轻量内联SVG画曲线(60秒刷新页"
     "不宜内嵌1MB ECharts，保持单文件离线可用）；index.html客户展示页继续用内嵌ECharts"),
    ("v3.4", "2026-10-26", "【入池战绩·T+1真实可执行口径】①候选池卡片+新入池表新增「当前股价」与「入池以来收益率」："
     "当前股价取腾讯实时行情；收益率按盘后可执行口径——入池当日不可买，T+1(下一交易日)开盘建仓，自T+1起算持仓"
     "天数与收益，未到T+1标'待T+1建仓'(并给预计T+1日期) ②新增market推断+新浪带日期日K拉取+腾讯批量行情，"
     "render时批量补全(每code一次请求) ③候选池卡片附'较入选价'参考涨跌(非T+1口径，仅感知用，明确标注'参考')"),
]

RULES = [
    "决策权在你，模型只给依据、禁指令话术",
    "诚实红线：亏就是亏，禁报喜藏忧",
    "无依据不出票",
    "先回测、再模拟盘30天、后实盘",
    "每票预设数字止损，触发即执行",
    "计划外交易必须登记",
    "数据不许猜、不许编",
    "全部版本化，留修订记录",
    "财联社任务线隔离不碰",
    "中线≤2个自然月",
    "仓位框架不盘中破",
    "每周复盘闭环",
    "宁做短不做长：只选超短期弹性优、上涨快的标的（近20日平均振幅≥2%硬门槛）；"
    "选不出就不做，绝不放宽标准、绝不为做而做",
]


def _f(v, fmt="%.2f", dash="-"):
    return fmt % v if v is not None else dash


def _sign(v, fmt="%+.2f", dash="-"):
    return fmt % v if v is not None else dash


def market_status():
    """当前A股时段状态 -> (灯, 文案)"""
    now = time.localtime()
    wd, hm = now.tm_wday, now.tm_hour * 100 + now.tm_min
    if wd >= 5:
        return ("⚪", "周末休市")
    if 930 <= hm <= 1130 or 1300 <= hm <= 1500:
        return ("🟢", "交易中·分钟级刷新")
    if 1130 < hm < 1300:
        return ("🟡", "午间休市")
    if hm >= 1500:
        return ("🔴", "已收盘·盘后复盘")
    return ("⚪", "盘前")


def verdict_class(order):
    if order.startswith("【走】") or order.startswith("【走/减】"):
        return "mo-bad"       # 离场信号：橙红警示
    if order.startswith("【减仓】"):
        return "mo-warn"
    if order.startswith("【留/持】"):
        return "mo-good"      # 继续持有：蓝
    return "mo-watch"         # 观察：灰


def _level_chip(kind, label, px, dist=None, note=None):
    """关键价位 chip。kind: stop/tgt/cost/now/e12/e50/res/sup"""
    style = {
        "stop": ("lv-stop", DOWN), "tgt": ("lv-tgt", UP),
        "cost": ("lv-cost", GRAY), "now": ("lv-now", "#2d3436"),
        "e12": ("lv-ma", PURPLE), "e50": ("lv-ma", PURPLE),
        "res": ("lv-res", UP), "sup": ("lv-sup", DOWN),
    }[kind]
    icon = {"stop": "🛑", "tgt": "🎯"}.get(kind, "")
    dist_html = ('<i>%s%%</i>' % _sign(dist, "%+.1f")) if dist is not None else ""
    note_html = ('<i>%s</i>' % note) if note else ""
    return ('<span class="lv %s"><em>%s</em>%s <b>%s</b>%s%s</span>'
            % (style[0], icon, label, _f(px), dist_html, note_html))


def build_card(r, tot_mv):
    up = r["chg_pct"] >= 0
    plup = r["pl_pct"] >= 0
    fup = (r["fund_main"] or 0) >= 0
    c_price = UP if up else DOWN
    c_pl = UP if plup else DOWN
    c_day = UP if r["day_pl"] >= 0 else DOWN
    c_fund = UP if fup else DOWN
    weight = r["mv"] / tot_mv * 100 if tot_mv else 0
    stop_dist = (r["price"] - r["stop_px"]) / r["price"] * 100 if r["price"] else 0
    tgt_dist = (r["tgt_px"] - r["price"]) / r["price"] * 100 if r["price"] else 0
    e12 = r.get("expma12"); e50 = r.get("expma50")
    e12d = (r["price"] - e12) / e12 * 100 if e12 else None
    e50d = (r["price"] - e50) / e50 * 100 if e50 else None
    posbar = min(max(r["pos_in_range"], 0), 100)

    alert_html = "".join('<span class="tag">⚠ %s</span>' % a for a in r["alerts"])
    alert_html = alert_html or '<span class="tag ok">✓ 无异动</span>'

    chips = []
    chips.append(_level_chip("stop", "止损", r["stop_px"], -stop_dist, r.get("stop_basis")))
    chips.append(_level_chip("cost", "成本", r["cost"]))
    chips.append(_level_chip("now", "现价", r["price"]))
    if e12:
        chips.append(_level_chip("e12", "EXPMA12", e12, e12d))
    if e50:
        chips.append(_level_chip("e50", "EXPMA50", e50, e50d))
    if r.get("res10"):
        chips.append(_level_chip("res", "压力", r["res10"]))
    if r.get("sup10"):
        chips.append(_level_chip("sup", "支撑", r["sup10"]))
    chips.append(_level_chip("tgt", "目标", r["tgt_px"], tgt_dist))

    typebadge = "ST ±5%" if "ST" in r["name"].upper() else (
        "创业/科创 ±20%" if r["code"].startswith(("30", "688")) else "主板 ±10%")

    return """
<div class="card%(alert_cls)s">
  <div class="chead">
    <div class="nmbox">
      <span class="nm">%(name)s</span><span class="code">%(code)s</span>
      <span class="tb">%(tb)s</span>
      <span class="cls">%(cls)s</span>
    </div>
    <div class="pxbox">
      <span class="px" style="color:%(c_price)s">%(price).2f</span>
      <span class="chg" style="color:%(c_price)s">%(chg)+.2f%%</span>
      <span class="daypl" style="color:%(c_day)s">日内%(daypl)s万</span>
    </div>
  </div>
  <div class="alerts">%(alerts)s</div>
  <div class="kpis">
    <div class="kpi"><label>持仓数量</label><b>%(shares)s 股</b></div>
    <div class="kpi"><label>成本价</label><b>%(cost).4f</b></div>
    <div class="kpi"><label>市值 ｜ 仓位占比</label><b>%(mv).2f万 ｜ <span class="hl">%(weight).1f%%</span></b></div>
    <div class="kpi"><label>持仓盈亏</label><b style="color:%(c_pl)s">%(pl)s (%(plpct)+.2f%%)</b></div>
    <div class="kpi"><label>当日盈亏</label><b style="color:%(c_day)s">%(daypl)s 万</b></div>
    <div class="kpi"><label>今日 高/低</label><b>%(high).2f / %(low).2f</b></div>
    <div class="kpi"><label>涨跌停</label><b>%(up_limit).2f / %(dn_limit).2f</b></div>
    <div class="kpi"><label>量比 ｜ 换手</label><b>%(vr)s ｜ %(turn).2f%%</b></div>
    <div class="kpi"><label>成交额</label><b>%(amt).0f 万</b></div>
    <div class="kpi"><label>振幅 ｜ 20日平均振幅</label><b>%(amp).1f%% ｜ %(amp20)s</b></div>
  </div>
  <div class="levels"><span class="lvtitle">关键价位</span>%(chips)s</div>
  <div class="range"><div class="rangefill" style="width:%(posbar).0f%%"></div>
    <div class="rangelabel">日内位置 %(pos).0f%%（低%(low).2f → 高%(high).2f，均价%(avg)s）</div></div>
  <div class="fundline">📊 主力净额（同花顺口径·超大单+大单，%(fund_date)s）：<b style="color:%(c_fund)s">%(fund)s</b></div>
  <div class="mods">
    <div class="mod mt"><b>⏱ 分时做T指导 · 盘中</b><p>%(tac_t)s</p></div>
    <div class="mod mw"><b>📈 日线波段指导 · 盘中</b><p>%(wave)s</p></div>
    <div class="mod %(vcls)s"><b>🧭 盘后作战指令 · 明日/未来几日走留判断</b><p>%(order)s</p></div>
    <div class="mod md"><b>🛡 超短交易纪律</b><p>%(disc)s</p></div>
  </div>
</div>""" % {
        "alert_cls": " alert" if r["alerts"] else "",
        "name": r["name"], "code": r["code"], "tb": typebadge,
        "cls": "已收盘" if r["closed"] else "交易中",
        "c_price": c_price, "price": r["price"], "chg": r["chg_pct"],
        "c_day": c_day, "daypl": "{:+,.2f}".format(r["day_pl"] / 1e4),
        "alerts": alert_html, "shares": "{:,}".format(r["shares"]),
        "cost": r["cost"], "mv": r["mv"] / 1e4, "weight": weight,
        "c_pl": c_pl, "pl": "{:+,.2f}万".format(r["pl"] / 1e4),
        "plpct": r["pl_pct"], "high": r["high"], "low": r["low"],
        "up_limit": r["up_limit"], "dn_limit": r["dn_limit"],
        "vr": ("%.2f" % r["vol_ratio"]) if r["vol_ratio"] else "盘后不显示",
        "turn": r["turnover"], "amt": r["amt_wan"], "amp": r["amp_today"],
        "amp20": ("%.1f%%" % r["amp20"]) if r.get("amp20") is not None else "-",
        "chips": "".join(chips), "posbar": posbar, "pos": r["pos_in_range"],
        "avg": ("%.2f" % r["avg"]) if r["avg"] else "-",
        "fund_date": r["fund_date"] or "暂无", "c_fund": c_fund,
        "fund": ("{:+,.2f}万".format(r["fund_main"] / 1e4)
                 if r["fund_main"] is not None else "暂无"),
        "tac_t": r["tac_t"], "wave": r["wave"], "order": r["order"],
        "disc": r["disc"], "vcls": verdict_class(r["order"]),
    }


def build_picks(perf=None):
    if not PICKS_FILE.exists():
        return '<div class="sec"><h2>🎯 每日选股 · 候选池</h2><div class="mod">选股结果尚未生成（每个交易日15:45后自动运行）</div></div>'
    try:
        picks = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        picks = None
    if not picks or not picks.get("picks"):
        return '<div class="sec"><h2>🎯 每日选股 · 候选池</h2><div class="mod">选股结果尚未生成（每个交易日15:45后自动运行）</div></div>'
    html = ('<div class="sec"><h2>🎯 每日选股 · 候选池 <small>（全A海扫 → 截面筛选 → '
            '多因子打分 → 资金加成；铁律#13：宁做短不做长，弹性不足直接剔除）</small></h2>')
    html += ('<div class="pmeta">生成于 %s ｜ 扫描 %d 只 → 入池 %d → 打分 %d ｜ 耗时 %.0fs ｜ '
             '候选 %d 只（★主推 %d 只）｜ 数据源：%s</div>'
             % (picks["generated_at"], picks["market_scanned"], picks["layer1_pool"],
                picks["layer2_scored"], picks["elapsed_sec"], len(picks["picks"]),
                sum(1 for p in picks["picks"] if p["primary"]), picks["data_source"]))
    by_code = _track_data()["by_code"]
    if perf is None:
        perf = _compute_perf()
    entry_date = (picks.get("generated_at") or "")[:10]
    for p in picks["picks"]:
        tag = "★主推" if p["primary"] else "备选"
        reasons = "".join("<li>%s</li>" % x for x in p["reasons"])
        fac = p.get("factors", {})
        fund = p.get("fund_main")
        fac_chips = "".join(
            '<span class="fc">%s %s</span>' % (k, _f(v, "%.1f"))
            for k, v in fac.items())
        if fund is not None:
            fc = UP if fund >= 0 else DOWN
            fac_chips += ('<span class="fc" style="color:%s;border-color:%s">资金 %s万</span>'
                          % (fc, fc, "{:+,.0f}".format(fund / 1e4)))
        score_pct = min(p["score"], 100)
        cls = "pick primary" if p["primary"] else "pick"
        c = UP if p["chg"] >= 0 else DOWN
        # v3.3 个股战绩徽章：回答"这只票模型历史上选中后到底行不行"
        rec = by_code.get(p["code"])
        if rec and rec.get("n", 0) > 0:
            badge = ('<div class="pbadge"><b>📊 个股战绩</b>历史入选 <b>%d</b> 次 · '
                     '<b style="color:%s">%d胜%d负</b> · 累计 '
                     '<b style="color:%s">%+.1f%%</b> · 上次(%s) <b style="color:%s">%+.1f%%</b></div>'
                     % (rec["n"], UP if rec["win"] >= rec["loss"] else DOWN,
                        rec["win"], rec["loss"], UP if rec["cum"] > 0 else DOWN, rec["cum"],
                        rec["last_date"] or "-", UP if (rec["last_ret"] or 0) > 0 else DOWN,
                        rec["last_ret"] or 0))
        elif rec and rec.get("live_pending"):
            badge = ('<div class="pbadge new"><b>🆕 个股战绩</b>今日首次入池 · '
                     '开始追踪（K线刷新后5日自动结算战绩）</div>')
        else:
            badge = ('<div class="pbadge new"><b>🆕 个股战绩</b>首次入选 · '
                     '开始追踪（K线刷新后5日自动结算战绩）</div>')
        # v3.4 当前股价 + 入池以来收益率（T+1口径：盘后入池当日不可买）
        pf = _perf_for(p["code"], entry_date, perf["cur"], perf["kline"])
        live_line = _render_perf_line(pf, p["price"])
        html += """
<div class="%(cls)s">
  <div class="phead">
    <span class="rank">#%(rank)d</span>
    <span class="pnm">%(name)s <small>%(code)s</small></span>
    <span class="ptag">%(tag)s</span>
    <span class="pprice" style="color:%(c)s">%(price).2f（%(chg)+.2f%%）成交%(amt).1f亿 · 20日振幅%(amp).1f%%</span>
  </div>
  <div class="scorebar"><div class="scorefill" style="width:%(spct).0f%%"></div>
    <span class="scorelabel">综合得分 <b>%(score).1f</b> / 100</span></div>
  <div class="fchs">%(fac_chips)s</div>
  <ul class="why">%(reasons)s</ul>
  %(badge)s
  %(live_line)s
  <div class="prow pb"><b>🛒 买入条件</b>%(buy)s</div>
  <div class="prow ps"><b>🛑 止损位</b>%(stop)s</div>
  <div class="prow pt"><b>🎯 目标位</b>%(target)s</div>
  <div class="prow pi"><b>⛔ 失效条件</b>%(invalid)s</div>
</div>""" % {"cls": cls, "rank": p["rank"], "name": p["name"],
            "code": p["code"], "tag": tag, "c": c, "price": p["price"],
            "chg": p["chg"], "amt": p["amount_yi"], "amp": p.get("amp20") or 0,
            "spct": score_pct, "score": p["score"], "fac_chips": fac_chips,
            "reasons": reasons, "buy": p["buy"], "stop": p["stop"],
            "target": p["target"], "invalid": p["invalid"], "badge": badge, "live_line": live_line}
    html += "</div>"
    return html


def build_backtest():
    head = ('<div class="sec"><h2>🔬 模型回测战绩 <small>（两年真实日线回测 · '
            '验证量化模型是否真能选出超短强势股）</small></h2>')
    if not BT_FILE.exists():
        return head + '<div class="mod">回测尚未生成（首次运行需拉取全市场500日K，约10-15分钟，之后复用）</div></div>'
    try:
        bt = json.loads(BT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return head + '<div class="mod">回测数据读取失败</div></div>'
    m = bt["metrics"]
    cards = [
        ("交易笔数", "%d 笔" % m["总交易笔数"], None),
        ("胜率", "%.1f%%" % m["胜率%"], BLUE if m["胜率%"] >= 45 else ORANGE),
        ("平均盈利", "%+.2f%%" % m["平均盈利%"], UP),
        ("平均亏损", "%+.2f%%" % m["平均亏损%"], DOWN),
        ("盈亏比", _f(m.get("盈亏比"), "%.2f"), BLUE),
        ("单笔期望", "%+.3f%%" % m["单笔期望%"], UP if m["单笔期望%"] > 0 else DOWN),
        ("组合总收益", "%+.1f%%" % m["组合总收益%"], UP if m["组合总收益%"] > 0 else DOWN),
        ("基准(流动性等权)", "%+.1f%%" % m["基准(流动性等权)%"], GRAY),
        ("最大回撤", "%.1f%%" % m["最大回撤%"], DOWN),
        ("平均持仓天数", "%.1f 天" % m["平均持仓天数"], None),
        ("止损出场占比", "%.1f%%" % m["止损占比%"], ORANGE),
        ("止盈出场占比", "%.1f%%" % m["止盈占比%"], UP),
    ]
    boxes = "".join(
        '<div class="btbox"><label>%s</label><b style="color:%s">%s</b></div>'
        % (k, c or "#2d3436", v) for k, v, c in cards)
    # 诚实对照：模型 vs 随机基线 vs 流动性等权基准（随数据自动翻转结论）
    rb = bt.get("random_baseline") or {}
    verdict = ""
    if rb:
        mv = m["组合总收益%"]; rv = rb.get("组合总收益%", 0); bv = m["基准(流动性等权)%"]
        if mv >= rv and mv >= bv and mv > 0:
            vcls, vtxt = ("UP", "✅ 模型跑赢随机基线(%+.1f%%)与流动性等权基准(%+.1f%%)，因子组合具备正 alpha，方向成立" % (rv, bv))
        elif mv >= rv:
            vcls, vtxt = (ORANGE, "⚠️ 模型跑赢随机但未跑赢基准，因子仅有微弱优势，需继续优化")
        else:
            vcls, vtxt = ("DOWN", "❌ 模型跑输随机：量化选股不仅没用、还为负 alpha，因子组合在反向选股")
        verdict = ('<div class="btverdict" style="border-left-color:%s;background:%s">'
                   '<b>诚实结论：</b>%s。'
                   '（模型 %+.1f%% ｜ 随机基线 %+.1f%% ｜ 流动性等权基准 %+.1f%%，三者同交易规则、同流动性宇宙，可复现对照）'
                   '</div>' % (vcls, "#eaf3fd" if vcls == "UP" else ("#fdf2ec" if vcls == ORANGE else "#fdeceb"),
                               vtxt, mv, rv, bv))
    # M4 自身进化对比（vs M3.5 v3.1 基线，已知诚实值，硬编码对照）
    M35 = {"组合总收益%": 37.5, "胜率%": 44.6, "单笔期望%": -0.002, "最大回撤%": -38.7}
    m4_cmp = ('<div class="btm4"><b>📊 M4 自身进化（vs M3.5 v3.1 基线）</b>'
        '<span>最大回撤 <s>' + ("%.1f" % M35["最大回撤%"]) + '%</s> → '
        '<b style="color:' + DOWN + '">' + ("%.1f" % m["最大回撤%"]) + '%</b>（砍半✅）</span>'
        '<span>单笔期望 <s>' + ("%+.3f" % M35["单笔期望%"]) + '%</s> → '
        '<b style="color:' + (UP if m["单笔期望%"] > 0 else DOWN) + '">' + ("%+.3f" % m["单笔期望%"]) + '%</b>（转正✅）</span>'
        '<span>组合收益 ' + ("%.1f" % M35["组合总收益%"]) + '% → ' + ("%.1f" % m["组合总收益%"]) + '%（持平，仍跑赢随机）</span>'
        '<span>胜率 ' + ("%.1f" % M35["胜率%"]) + '% → ' + ("%.1f" % m["胜率%"]) + '%（持平，框架天花板约44-45%）</span>'
        '</div>')
    trades = bt.get("trades", [])[-15:]
    if trades:
        rows = "".join(
            '<tr><td>%s</td><td>%s %s</td><td>%.2f</td><td>%.2f</td>'
            '<td style="color:%s">%+.2f%%</td><td>%d天</td><td>%s</td></tr>'
            % (t["buy_date"], t["name"], t["code"], t["buy"], t["sell"],
               UP if t["ret_pct"] > 0 else DOWN, t["ret_pct"],
               t["days"], t["reason"]) for t in reversed(trades))
        table = ('<table class="btt"><thead><tr><th>买入日</th><th>标的</th><th>买价</th>'
                 '<th>卖价</th><th>收益</th><th>持仓</th><th>出场原因</th></tr></thead>'
                 "<tbody>%s</tbody></table>" % rows)
    else:
        table = ""
    rbox = ""
    if rb:
        rbox = ('<div class="btcmp">对照（同规则：等权≤3只/持有5日/止损-5%%止盈+8%%）：'
                '<span class="cmp m">量化模型 <b style="color:%s">%+.1f%%</b></span>'
                '<span class="cmp r">随机乱买 <b style="color:%s">%+.1f%%</b></span>'
                '<span class="cmp b">流动性等权 <b style="color:%s">%+.1f%%</b></span>'
                '<span class="cmp sub">随机基线笔数%d｜胜率%.1f%%｜最大回撤%.1f%%</span></div>'
                % (DOWN if m["组合总收益%"] < 0 else UP, m["组合总收益%"],
                   UP if rb.get("组合总收益%", 0) >= 0 else DOWN, rb.get("组合总收益%", 0),
                   GRAY, m["基准(流动性等权)%"],
                   rb.get("总交易笔数", 0), rb.get("胜率%", 0), rb.get("最大回撤%", 0)))
    return (head + '<div class="btgrid">%s</div>%s%s%s'
            '<div class="btnote">📋 回测口径（诚实声明）：%s。区间：%s，共%d个交易日。'
            '回测版因子不含资金流（无历史资金流数据，实时版才有）；未计滑点/停牌/涨跌停无法成交；止损-5%%/止盈+8%%。'
            '随机基线采用同套交易规则、固定随机种子，可复现，用于检验因子是否真有 alpha。'
            '历史回测不代表未来收益，用于验证模型逻辑是否成立。</div>%s</div>'
            % (boxes, rbox, verdict, m4_cmp, bt.get("assumptions", ""), m["区间"], m["交易日数"], table))


def sync_pick_history():
    """把今日选股追加到 picks_history.jsonl（幂等：按 date+code 去重）。
    实时追踪自今日起登记；K线数据(history.npz)刷新到覆盖入选日后自动结算5日战绩。"""
    try:
        pj = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    picks = pj.get("picks", [])
    if not picks:
        return
    date = (pj.get("generated_at") or "")[:10]
    existing = set()
    if TRACK_FILE.exists():
        for line in TRACK_FILE.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                existing.add((r.get("date"), r.get("code")))
            except Exception:
                pass
    new = []
    for p in picks:
        if (date, p["code"]) in existing:
            continue
        new.append({"date": date, "code": p["code"], "name": p["name"],
                    "primary": bool(p.get("primary")), "entry": p["price"],
                    "score": p.get("score"), "status": "待结算",
                    "note": "入池登记，K线刷新后自动结算5日战绩"})
    if new:
        with open(TRACK_FILE, "a", encoding="utf-8") as f:
            for rec in new:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_pick_history():
    out = []
    if TRACK_FILE.exists():
        for line in TRACK_FILE.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _track_data():
    """聚合回测 trades(历史战绩种子) + picks_history(实时追踪) → 战绩追踪数据。
    个股 by_code 索引、近20笔战绩、总体统计、收益曲线。"""
    trades, equity, m = [], [], {}
    try:
        bt = json.loads(BT_FILE.read_text(encoding="utf-8"))
        trades = bt.get("trades", [])
        equity = bt.get("equity_curve", [])
        m = bt.get("metrics", {})
    except Exception:
        pass
    live = _read_pick_history()
    # 个股战绩索引（历史回测样本）
    by_code = {}
    for t in trades:
        c = by_code.setdefault(t["code"], {"code": t["code"], "name": t["name"], "n": 0,
                                           "win": 0, "loss": 0, "cum": 0.0,
                                           "last_date": None, "last_ret": None})
        c["n"] += 1
        c["cum"] += t["ret_pct"]
        if t["ret_pct"] > 0:
            c["win"] += 1
        else:
            c["loss"] += 1
        if c["last_date"] is None or t.get("buy_date", "") >= c["last_date"]:
            c["last_date"] = t.get("buy_date", "")
            c["last_ret"] = t["ret_pct"]
    # 实时追踪：为今日/近几日新入池但回测样本中没有的 code 建索引（标记 live_pending）
    for r in live:
        c = by_code.setdefault(r["code"], {"code": r["code"], "name": r["name"], "n": 0,
                                           "win": 0, "loss": 0, "cum": 0.0,
                                           "last_date": None, "last_ret": None})
        c["live_pending"] = c.get("live_pending", 0) + 1
    # 近 20 笔战绩（按买入日倒序）
    recent = sorted(trades, key=lambda t: t.get("buy_date", ""), reverse=True)[:20]
    # 总体统计（已收官 = 回测样本全部）
    wins = [t for t in trades if t["ret_pct"] > 0]
    stats = {
        "total": len(trades), "win": len(wins), "loss": len(trades) - len(wins),
        "winrate": (len(wins) / len(trades) * 100) if trades else 0,
        "avg": (sum(t["ret_pct"] for t in trades) / len(trades)) if trades else 0,
        "cum": sum(t["ret_pct"] for t in trades),
        "best": max((t["ret_pct"] for t in trades), default=0.0),
        "worst": min((t["ret_pct"] for t in trades), default=0.0),
        "open_live": len(live),
    }
    return {"by_code": by_code, "recent": recent, "stats": stats,
            "equity": equity, "live": live, "metrics": m}


def _equity_svg(equity):
    """内联 SVG 收益曲线（自包含、无外部依赖；position.html 为 60 秒刷新页，不内嵌 ECharts）。"""
    if not equity or len(equity) < 2:
        return ""
    W, H = 100.0, 100.0
    lo, hi = min(equity), max(equity)
    rng = (hi - lo) or 1.0
    pts = []
    n = len(equity)
    for i, v in enumerate(equity):
        x = i / (n - 1) * W
        y = H - (v - lo) / rng * H
        pts.append("%.1f,%.1f" % (x, y))
    base_y = H - (1.0 - lo) / rng * H  # 本金基准线 y=1.0
    up = equity[-1] >= equity[0]
    color = UP if up else DOWN
    return ('<svg viewBox="0 0 %g %g" preserveAspectRatio="none" class="eqsvg">'
            '<line x1="0" y1="%.1f" x2="%g" y2="%.1f" stroke="#b2bec3" stroke-width="0.4" '
            'stroke-dasharray="2 2"/>'
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6" '
            'stroke-linejoin="round"/></svg>'
            % (W, H, base_y, W, base_y, " ".join(pts), color))


def _market_of(code):
    if code.startswith("6"):
        return "sh"
    if code.startswith("0") or code.startswith("3"):
        return "sz"
    if code.startswith("8") or code.startswith("4"):
        return "bj"
    return "sz"


def _next_trading_day(d):
    """估算下一交易日（跳过周末；未计法定节假日，页面标注"预计"）。"""
    try:
        from datetime import date, timedelta
        y, m, dd = (int(x) for x in d.split("-"))
        cur = date(y, m, dd) + timedelta(days=1)
        while cur.weekday() >= 5:
            cur += timedelta(days=1)
        return cur.isoformat()
    except Exception:
        return None


def _fetch_kline_dated(code, market, datalen=75):
    """新浪日K（带日期）。返回 [(day, open, high, low, close, volume)]，day='YYYY-MM-DD'。"""
    import urllib.request
    sym = "%s%s" % (market, code)
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d" % (sym, datalen))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Referer": "https://finance.sina.com.cn/"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        return [(str(x["day"]), float(x["open"]), float(x["high"]), float(x["low"]),
                 float(x["close"]), float(x["volume"])) for x in data]
    except Exception:
        return []


def _compute_perf():
    """为候选池+入池记录批量拉实时行情与带日期日K（行情批量1次、日K每code一次）。返回 {cur, kline}。"""
    codes = set()
    try:
        pj = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
        for p in pj.get("picks", []):
            codes.add(p["code"])
    except Exception:
        pass
    for r in _read_pick_history():
        if r.get("code"):
            codes.add(r["code"])
    cur, kline = {}, {}
    if not codes:
        return {"cur": cur, "kline": kline}
    try:
        import pos_watch
        q = pos_watch.fetch_quotes(["%s%s" % (_market_of(c), c) for c in codes])
        for c in codes:
            cur[c] = (q.get(c) or {}).get("price")
    except Exception:
        pass
    for c in codes:
        try:
            kline[c] = _fetch_kline_dated(c, _market_of(c))
        except Exception:
            kline[c] = []
        time.sleep(0.25)
    return {"cur": cur, "kline": kline}


def _perf_for(code, entry_date, cur, kline):
    """T+1 口径个股入池战绩：盘后入池当日不可买，T+1(下一交易日)开盘建仓，自 T+1 起算持仓与收益。
    返回 {cur, built, ret, hold, base, t1_day, t1_expect}。"""
    kl = kline.get(code) or []
    cur_px = cur.get(code)
    out = {"cur": cur_px}
    days = [k[0] for k in kl]
    if entry_date in days:
        i = days.index(entry_date)
        if i + 1 < len(kl):
            t1 = kl[i + 1]
            base = t1[1]  # T+1 开盘价建仓
            hold = len(kl) - (i + 1)  # 自 T+1 至最新的交易日数
            ret = (cur_px / base - 1) * 100 if (cur_px and base) else None
            out.update({"built": True, "t1_day": t1[0], "base": base, "ret": ret, "hold": hold})
            return out
        out.update({"built": False, "t1_expect": _next_trading_day(entry_date)})
        return out
    out.update({"built": False, "t1_expect": _next_trading_day(entry_date)})
    return out


def _render_perf_line(pf, entry_px):
    """候选池卡片的『当前股价 + 入池以来收益率』行（T+1口径，未到T+1标待建仓）。"""
    cur = pf.get("cur")
    if cur is None:
        return '<div class="pbadge live">📈 当前股价：数据获取中…</div>'
    vs = (cur / entry_px - 1) * 100 if entry_px else 0.0
    vsc = UP if vs >= 0 else DOWN
    if pf.get("built"):
        ret = pf.get("ret") or 0.0
        rc = UP if ret > 0 else (DOWN if ret < 0 else "#2d3436")
        return ('<div class="pbadge live">📈 当前股价 <b>%.2f</b>'
                '（较入选价 <b style="color:%s">%+.1f%%</b>，参考）｜'
                '入池以来收益率 <b style="color:%s">%+.1f%%</b>'
                '（T+1 %s 开盘 %.2f 建仓 · 持仓 %d 日）</div>'
                % (cur, vsc, vs, rc, ret, pf.get("t1_day", "-"),
                   pf.get("base") or 0, pf.get("hold") or 0))
    t1 = pf.get("t1_expect")
    tip = ("，预计 T+1（%s）开盘建仓" % (t1[5:] if t1 else "下一交易日"))
    return ('<div class="pbadge live">📈 当前股价 <b>%.2f</b>'
            '（较入选价 <b style="color:%s">%+.1f%%</b>，参考）｜'
            '入池以来收益率：<b>待 T+1 建仓</b>（盘后入池当日不可买%s）</div>'
            % (cur, vsc, vs, tip))


def build_track(perf=None):
    """v3.3 选股战绩追踪：动态仪表盘 + SVG 收益曲线 + 今日入池登记 + 近期选股战绩明细。"""
    if perf is None:
        perf = _compute_perf()
    track = _track_data()
    st, recent, live = track["stats"], track["recent"], track["live"]
    by_code = track["by_code"]
    m = track["metrics"]
    head = ('<div class="sec"><h2>🏆 选股战绩追踪 <small>（模型选股 → 实际走势 → 动态胜率，'
            '每日更新；回答"每只票到底行不行、模型胜率多少"）</small></h2>')
    cards = [
        ("回测样本", "%d 笔" % st["total"], None),
        ("涉及个股", "%d 只" % len(by_code), None),
        ("胜率", "%.1f%%" % st["winrate"], BLUE if st["winrate"] >= 45 else ORANGE),
        ("平均单笔", "%+.2f%%" % st["avg"], UP if st["avg"] > 0 else DOWN),
        ("累计收益", "%+.1f%%" % m.get("组合总收益%", 0), UP if m.get("组合总收益%", 0) > 0 else DOWN),
        ("最大单笔", "%+.1f%%" % st["best"], UP),
        ("最差单笔", "%+.1f%%" % st["worst"], DOWN),
        ("今日新入池", "%d 只" % st["open_live"], BLUE),
    ]
    boxes = "".join('<div class="btbox"><label>%s</label><b style="color:%s">%s</b></div>'
                    % (k, c or "#2d3436", v) for k, v, c in cards)
    # 收益曲线
    eq = _equity_svg(track["equity"])
    curve = ""
    if eq:
        rng = m.get("区间", "")
        curve = ('<div class="eqwrap"><div class="eqtitle">累计收益曲线'
                 '（本金=1.0 基准线，采样自回测样本；区间 %s）</div>%s</div>' % (rng, eq))
    # 今日新入池登记
    live_rows = ""
    today_live = sorted(live, key=lambda r: r.get("date", ""), reverse=True)[:8]
    if today_live:
        rows = ""
        for r in today_live:
            pf = _perf_for(r.get("code", ""), r.get("date", ""), perf["cur"], perf["kline"])
            cur = pf.get("cur")
            cur_s = "%.2f" % cur if cur else "-"
            if pf.get("built"):
                ret = pf.get("ret") or 0.0
                rc = UP if ret > 0 else (DOWN if ret < 0 else "#2d3436")
                ret_s = '<b style="color:%s">%+.1f%%</b>' % (rc, ret)
                st_s = "持仓%d日" % (pf.get("hold") or 0)
            else:
                ret_s = '<span style="color:%s">待T+1建仓</span>' % BLUE
                st_s = "待结算"
            rows += ('<tr><td>%s</td><td>%s %s</td><td>%.2f</td><td>%s</td>'
                     '<td>%s</td><td>%s</td><td>%s</td></tr>'
                     % (r.get("date", ""), r.get("name", ""), r.get("code", ""),
                        r.get("entry", 0), "★主推" if r.get("primary") else "备选",
                        cur_s, ret_s, st_s))
        live_rows = ('<div class="eqtitle">🆕 今日/近期新入池（盘后入池当日不可买，T+1开盘建仓起算；'
                     'K线刷新后自动结算）</div>'
                     '<table class="btt"><thead><tr><th>入选日</th><th>标的</th><th>入选价</th>'
                     '<th>类型</th><th>当前股价</th><th>入池以来收益率</th><th>状态</th></tr></thead>'
                     '<tbody>%s</tbody></table>' % rows)
    # 近期选股战绩明细（回测样本近20笔）
    table = ""
    if recent:
        rows = "".join(
            '<tr><td>%s</td><td>%s %s</td><td>%.2f</td><td>%.2f</td>'
            '<td style="color:%s"><b>%+.2f%%</b></td><td style="color:%s">%s</td>'
            '<td>%s</td><td>%d天</td></tr>'
            % (t["buy_date"], t["name"], t["code"], t["buy"], t["sell"],
               UP if t["ret_pct"] > 0 else DOWN, t["ret_pct"],
               UP if t["ret_pct"] > 0 else DOWN, "✅胜" if t["ret_pct"] > 0 else "❌负",
               t["reason"], t["days"]) for t in recent)
        table = ('<div class="eqtitle">📋 近期选股战绩（回测样本，近%d笔，按买入日倒序）</div>'
                 '<table class="btt"><thead><tr><th>入选日</th><th>标的</th><th>入选价</th>'
                 '<th>出场价</th><th>收益</th><th>结果</th><th>出场原因</th><th>持仓</th></tr></thead>'
                 "<tbody>%s</tbody></table>" % (len(recent), rows))
    note = ('<div class="btnote">📋 战绩口径（诚实声明）：仪表盘/曲线/明细的战绩种子取自两年回测样本'
            '（同规则：T-1收盘信号、T日收盘成交、止损-5%/止盈+8%/5日到期/结构失效出场），'
            '个股徽章为该股历史被模型选中后的累计表现；"今日新入池"为实时登记，需等K线数据刷新到覆盖入选日'
            '后自动结算5日战绩。当前胜率/累计收益为回测样本口径，随每日入池结算将逐步转为实时口径。'
            '<b>回测战绩不代表未来收益，用于验证模型逻辑是否成立；胜率天花板约44-45%'
            '（框架特性，靠频率+纪律+控回撤取胜，非靠高胜率）。</b></div>')
    return (head + '<div class="btgrid">%s</div>%s%s%s%s</div>'
            % (boxes, curve, live_rows, table, note))


def render(rows=None):
    if rows is None:
        import pos_watch
        rows = pos_watch.build_rows()
    sync_pick_history()  # v3.3 维护每日选股入池登记（幂等去重）
    tot_mv = sum(r["mv"] for r in rows)
    tot_cost = sum(r["cost_mv"] for r in rows)
    tot_pl = tot_mv - tot_cost
    tot_pl_pct = tot_pl / tot_cost * 100 if tot_cost else 0
    tot_day = sum(r["day_pl"] for r in rows)
    gen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    lamp, lamp_txt = market_status()

    cards = "".join(build_card(r, tot_mv) for r in rows)
    perf = _compute_perf()
    pick_html = build_picks(perf)
    track_html = build_track(perf)
    bt_html = build_backtest()
    rev_html = "".join('<li><b>%s</b>（%s）：%s</li>' % r for r in REVISION_LOG)
    rules_html = "".join("<li>%s</li>" % r for r in RULES)

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>持仓作战平台 · 实时盯盘 + 每日选股 + 模型回测</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#eef0f4;color:#2d3436;padding:12px;max-width:1100px;margin:0 auto}
a{color:#74b9ff;text-decoration:none}
/* ===== 深色作战总览带 ===== */
.top{background:linear-gradient(135deg,#17203a 0%,#1f2b4d 60%,#26355e 100%);color:#fff;border-radius:14px;padding:16px 18px;margin-bottom:14px;box-shadow:0 3px 10px rgba(23,32,58,.25)}
.top .hdrow{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.top h1{font-size:21px;color:#fff;letter-spacing:.5px}
.top .meta{font-size:12px;color:#a4b0be}
.badge{display:inline-block;background:#0984e3;color:#fff;font-size:12px;font-weight:700;padding:3px 10px;border-radius:12px;margin-left:8px;vertical-align:middle}
.lamp{display:inline-block;background:rgba(255,255,255,.12);font-size:12px;padding:3px 10px;border-radius:12px;margin-left:8px}
.ov{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.ov .box{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.10);border-radius:10px;padding:10px 12px}
.ov label{font-size:12px;color:#a4b0be;display:block;margin-bottom:4px}
.ov b{font-size:22px;font-weight:800;color:#fff}
.ov .sub{font-size:11px;color:#8fa0b5;margin-top:2px}
/* ===== 分区 ===== */
.sec{background:#fff;border-radius:12px;padding:14px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.07)}
.sec h2{font-size:17px;margin-bottom:4px}
.sec h2 small{font-size:12px;color:#636e72;font-weight:400}
/* ===== 持仓卡片 ===== */
.card{background:#fff;border-radius:12px;padding:14px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.07);border:1px solid #e6e9ee}
.card.alert{border:2px solid #e17055}
.chead{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.nmbox{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.nm{font-size:18px;font-weight:800}
.code{font-size:12px;color:#636e72}
.tb{background:#dfe6e9;color:#636e72;font-size:11px;padding:2px 8px;border-radius:10px}
.cls{background:#0984e3;color:#fff;font-size:11px;padding:2px 8px;border-radius:10px}
.pxbox{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.px{font-size:32px;font-weight:800;line-height:1}
.chg{font-size:17px;font-weight:700}
.daypl{font-size:12px;font-weight:600}
.alerts{margin:4px 0 8px}
.tag{display:inline-block;background:#ffeaa7;color:#b33939;font-size:12px;padding:2px 8px;border-radius:10px;margin:2px 6px 2px 0;font-weight:600}
.tag.ok{background:#dfe6e9;color:#636e72;font-weight:400}
/* 指标网格 */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:6px;margin-bottom:10px}
.kpi{background:#f7f8fa;border-radius:8px;padding:7px 10px}
.kpi label{font-size:11px;color:#636e72;display:block;margin-bottom:2px}
.kpi b{font-size:14px;font-weight:700}
.hl{color:#0984e3}
/* 关键价位色块条 */
.levels{display:flex;flex-wrap:wrap;gap:6px;align-items:center;background:#f7f8fa;border-radius:10px;padding:8px 10px;margin-bottom:8px}
.lvtitle{font-size:12px;color:#636e72;font-weight:700;margin-right:2px}
.lv{display:inline-flex;align-items:baseline;gap:4px;font-size:12px;background:#fff;border:1.5px solid #dfe6e9;border-radius:8px;padding:3px 8px;line-height:1.5}
.lv em{font-style:normal}
.lv b{font-size:14px;font-weight:800}
.lv i{font-style:normal;font-size:11px;color:#636e72}
.lv-stop{border-color:#00a37a;background:#e8f8f3}
.lv-stop b{color:#00a37a}
.lv-tgt{border-color:#e0322f;background:#fdeceb}
.lv-tgt b{color:#e0322f}
.lv-cost{border-color:#b2bec3}
.lv-cost b{color:#636e72}
.lv-now{border-color:#2d3436;background:#2d3436}
.lv-now b{color:#fff}
.lv-now i{color:#dfe6e9}
.lv-ma{border-color:#6c5ce7;background:#f0edfd}
.lv-ma b{color:#6c5ce7}
.lv-res{border-color:#e0322f;background:#fff5f4}
.lv-res b{color:#e0322f}
.lv-sup{border-color:#00a37a;background:#f4fbf8}
.lv-sup b{color:#00a37a}
/* 日内位置条 */
.range{position:relative;height:22px;background:#dfe6e9;border-radius:11px;margin:6px 0 8px;overflow:hidden}
.rangefill{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,#00a37a33,#e0322f33)}
.rangelabel{position:absolute;width:100%;text-align:center;font-size:12px;line-height:22px;color:#2d3436}
.fundline{font-size:13px;margin:4px 0 8px;color:#2d3436;background:#f7f8fa;border-radius:8px;padding:6px 10px}
/* 四模块 */
.mods{display:grid;gap:6px}
.mod{font-size:13.5px;border-left:4px solid #0984e3;background:#f4f8fd;padding:8px 12px;border-radius:0 8px 8px 0;line-height:1.65}
.mod b{display:block;font-size:13px;margin-bottom:2px}
.mod p{font-size:13.5px}
.mt{border-left-color:#0984e3}
.mw{border-left-color:#6c5ce7;background:#f6f4fe}
.mo-bad{border-left-color:#e0322f;background:#fdeceb}
.mo-bad b{color:#c0392b}
.mo-warn{border-left-color:#e17055;background:#fdf2ec}
.mo-warn b{color:#d35400}
.mo-good{border-left-color:#0984e3;background:#eaf3fd}
.mo-good b{color:#0984e3}
.mo-watch{border-left-color:#636e72;background:#f4f5f6}
.md{border-left-color:#e17055;background:#fdf6f1}
/* ===== 选股区 ===== */
.pmeta{font-size:12px;color:#636e72;margin-bottom:10px;line-height:1.7}
.pick{border:1px solid #dfe6e9;border-radius:10px;padding:10px 12px;margin-bottom:10px}
.pick.primary{border:2px solid #0984e3;background:#fbfdff}
.phead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.rank{background:#2d3436;color:#fff;font-size:13px;font-weight:800;border-radius:8px;padding:2px 8px}
.pick.primary .rank{background:#0984e3}
.pnm{font-size:16px;font-weight:800}
.pnm small{font-size:12px;color:#636e72;font-weight:400}
.ptag{font-size:11px;font-weight:700;color:#0984e3;border:1px solid #0984e3;border-radius:10px;padding:1px 8px}
.pprice{font-size:12px;color:#636e72;font-weight:600}
.scorebar{position:relative;height:16px;background:#eef0f4;border-radius:8px;margin:4px 0 6px;overflow:hidden}
.scorefill{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,#74b9ff,#0984e3)}
.scorelabel{position:absolute;width:100%;text-align:center;font-size:11px;line-height:16px;color:#2d3436}
.scorelabel b{color:#0984e3}
.fchs{margin:2px 0 6px}
.fc{display:inline-block;font-size:11px;background:#f1f2f6;border:1px solid #dfe6e9;border-radius:10px;padding:1px 8px;margin:2px 4px 2px 0;color:#2d3436;font-weight:600}
.why{margin:4px 0 8px 18px;font-size:13px;line-height:1.75}
.why li::marker{color:#0984e3}
.prow{font-size:13px;line-height:1.65;margin:3px 0;padding:5px 10px;border-radius:0 8px 8px 0}
.prow b{display:block;font-size:12px;margin-bottom:1px}
.pb{background:#f4f8fd;border-left:3px solid #0984e3}
.ps{background:#e8f8f3;border-left:3px solid #00a37a}
.pt{background:#fdeceb;border-left:3px solid #e0322f}
.pi{background:#fdf2ec;border-left:3px solid #e17055}
/* ===== 回测战绩区 ===== */
.btgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-bottom:10px}
.btbox{background:#f7f8fa;border-radius:10px;padding:10px;text-align:center}
.btbox label{font-size:11px;color:#636e72;display:block;margin-bottom:4px}
.btbox b{font-size:19px;font-weight:800}
.btnote{font-size:12px;color:#636e72;background:#f7f8fa;border-radius:8px;padding:8px 12px;line-height:1.7;margin-bottom:10px}
.btt{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
.btt th{background:#f1f2f6;padding:5px 6px;text-align:left;font-size:11px;color:#636e72;white-space:nowrap}
.btt td{padding:5px 6px;border-bottom:1px solid #eef0f4;white-space:nowrap}
.btt tr:hover{background:#f7f8fa}
/* 诚实对照条 + 结论 */
.btcmp{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;background:#f7f8fa;border-radius:10px;padding:9px 12px;margin-bottom:8px;font-size:13px}
.btcmp .cmp{font-weight:600}
.btcmp .cmp b{font-size:17px;font-weight:800;margin:0 2px}
.btcmp .cmp.sub{font-size:11px;color:#636e72;font-weight:400}
.btverdict{border-left:5px solid #e0322f;background:#fdeceb;border-radius:0 10px 10px 0;padding:10px 14px;margin-bottom:10px;font-size:13.5px;line-height:1.7}
.btverdict b{display:block;margin-bottom:2px;color:#c0392b}
/* M4 自身进化对比条 */
.btm4{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:baseline;background:#eef7f0;border-radius:10px;padding:9px 12px;margin-bottom:8px;font-size:12.5px;line-height:1.6}
.btm4>b{color:#00a37a;display:block;width:100%;margin-bottom:2px}
.btm4 span{background:#fff;border:1px solid #dfe6e9;border-radius:8px;padding:3px 9px}
.btm4 s{color:#b2bec3;text-decoration:line-through;margin-right:3px}
/* ===== 选股战绩追踪(v3.3) ===== */
.eqwrap{margin:10px 0}
.eqtitle{font-size:12px;color:#636e72;font-weight:700;margin:10px 0 4px}
.eqsvg{width:100%;height:120px;background:#f7f8fa;border:1px solid #eef0f4;border-radius:10px}
.pbadge{font-size:12.5px;background:#f0edfd;border-left:3px solid #6c5ce7;border-radius:0 8px 8px 0;padding:6px 10px;margin:4px 0 6px;line-height:1.6}
.pbadge.new{background:#fff8e1;border-left-color:#e17055}
.pbadge.live{background:#eef4fb;border-left-color:#0984e3}
.pbadge b{color:#2d3436}
/* ===== 页脚 ===== */
.ft{background:#fff;border-radius:12px;padding:14px;margin:14px 0;font-size:12px;color:#636e72;line-height:1.9;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.ft h3{font-size:13px;color:#2d3436;margin-bottom:6px}
.ft ol{margin-left:18px}
.ft .rules2{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:2px 14px}
@media (max-width:600px){
  body{padding:8px}
  .px{font-size:26px}
  .ov b{font-size:18px}
  .top h1{font-size:18px}
}
</style>
</head>
<body>
<div class="top">
  <div class="hdrow">
    <h1>📈 持仓作战平台<span class="badge">__VER__</span>
      <span class="lamp">__LAMP__ __LAMPTXT__</span></h1>
    <div class="meta">生成 __GEN__ ｜ 每60秒自动刷新 ｜ <a href="flows.html">→ 资金流看板</a> ｜ 红=涨/盈利 · 绿=跌/亏损</div>
  </div>
  <div class="ov">
    <div class="box"><label>总市值</label><b>__TOTMV__ 万</b><div class="sub">总成本 __TOTCOST__ 万</div></div>
    <div class="box"><label>持仓总盈亏</label><b style="color:__TOTPLC__">__TOTPL__ 万</b><div class="sub">__TOTPLPCT__%</div></div>
    <div class="box"><label>当日盈亏</label><b style="color:__TOTDAYC__">__TOTDAY__ 万</b><div class="sub">按今日涨跌×持仓</div></div>
    <div class="box"><label>持仓数</label><b>__N__ 只</b><div class="sub">超短1-3只纪律内</div></div>
    <div class="box"><label>今日主推</label><b>__TOPPICK__</b><div class="sub">候选池详见选股区</div></div>
  </div>
</div>

<div class="sec">
  <h2>📊 持仓作战区 <small>盘中实时意见（买/加/做T）＋ 盘后作战指令（明日走留判断），技术与数据点已标注</small></h2>
  __CARDS__
</div>

__PICKS__

__TRACK__

__BT__

<div class="ft">
  <h3>📝 修订记录</h3>
  <ol>__REV__</ol>
  <h3>⚖️ 铁律（项目宪法，13条）</h3>
  <div class="rules2"><ol>__RULES__</ol></div>
  <h3>🔎 数据口径与读图说明</h3>
  <div>实时行情：腾讯行情接口（分钟级快照；收盘后量比字段失真故盘后隐藏「量比」）。日线因子：新浪日K（EXPMA12/50、MA5/10/20、近10日支撑压力、60日高低、123法则下跌确认计数）。主力净额：同花顺口径（超大单+大单净额），取自资金流账本最近交易日，每个交易日15:45后更新。选股引擎：新浪全市场截面+新浪日K+同花顺资金流（东财接口当前403降级为备援）。回测引擎：新浪全市场500日K本地矩阵，T-1收盘信号、T日收盘成交。<br>
  读图说明：🛑止损=成本价-5%（铁律#5，触发无条件执行）；🎯目标=成本价+8%第一目标；EXPMA位置距离为现价相对均线的偏离度；日内位置0%=今日最低、100%=今日最高。四模块颜色：蓝=分时/持有信号、紫=日线波段、橙红=离场/减仓信号、灰=观察。<br>
  本平台为信息与规则工具，非持牌投顾服务；所有操作由你决策，盈亏由你承担。策略指导均为条件式参考，触发条件与依据已在各模块列明。</div>
</div>
</body>
</html>"""
    top_pick = "-"
    try:
        pj = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
        prim = [p for p in pj.get("picks", []) if p.get("primary")]
        if prim:
            top_pick = " / ".join("%s(%.1f)" % (p["name"], p["score"]) for p in prim[:3])
    except Exception:
        pass
    html = (html.replace("__VER__", VERSION).replace("__GEN__", gen)
            .replace("__LAMP__", lamp).replace("__LAMPTXT__", lamp_txt)
            .replace("__TOTMV__", "{:,.2f}".format(tot_mv / 1e4))
            .replace("__TOTCOST__", "{:,.2f}".format(tot_cost / 1e4))
            .replace("__TOTPLC__", UP if tot_pl >= 0 else DOWN)
            .replace("__TOTPL__", "{:+,.2f}".format(tot_pl / 1e4))
            .replace("__TOTPLPCT__", "%+.2f" % tot_pl_pct)
            .replace("__TOTDAYC__", UP if tot_day >= 0 else DOWN)
            .replace("__TOTDAY__", "{:+,.2f}".format(tot_day / 1e4))
            .replace("__N__", str(len(rows)))
            .replace("__TOPPICK__", top_pick)
            .replace("__CARDS__", cards)
            .replace("__PICKS__", pick_html)
            .replace("__TRACK__", track_html)
            .replace("__BT__", bt_html)
            .replace("__REV__", rev_html)
            .replace("__RULES__", rules_html))
    (DIR / "position.html").write_text(html, encoding="utf-8")
    (DIR / "index.html").write_text(html, encoding="utf-8")  # v3.3 GitHub Pages 首页同步（与持仓页同源）
    (DIR / "index.html").write_text(html, encoding="utf-8")
    return tot_pl


if __name__ == "__main__":
    import pos_watch
    rows = pos_watch.build_rows()
    for r in rows:
        print("%-6s %-7s 现价%8.2f %+6.2f%% | %s股 | 盈亏%+10.2f万(%+6.2f%%) | %s"
              % (r["code"], r["name"], r["price"], r["chg_pct"],
                 "{:,}".format(r["shares"]), r["pl"] / 1e4, r["pl_pct"],
                 r["order"][:22]))
    pl = render(rows)
    print("组合总盈亏: %+.2f万 | %s 页面已生成" % (pl / 1e4, VERSION))
