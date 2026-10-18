# -*- coding: utf-8 -*-
"""
同花顺口径资金流采集公共库（采集器 / 守护进程 / 看板共用）

数据源（均为同花顺官方接口，非估算）：
  1) stockpage.10jqka.com.cn funds API（免鉴权）
     -> 最近一个已收盘交易日的分单资金快照：超大单/大单/中单/小单净额
  2) quota-h.10jqka.com.cn fuyao single_kline（embedded token）
     -> 权威确定"最近已收盘交易日"日期，并记录当日收盘价/成交量/成交额

口径：主力净流入 = 超大单净(mass) + 大单净(big)   [同花顺个股页口径]
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
# 目录解析：优先环境变量 THS_DIR，否则取本文件所在目录
# （本地=/workspace/ths_daily；GitHub Actions=仓库检出目录，二者兼容）
DIR = Path(os.environ.get("THS_DIR") or Path(__file__).resolve().parent)
LEDGER = DIR / "flows.jsonl"
COLLECT_LOG = DIR / "collector.log"

STOCKS = [
    ("002491", "33", "通鼎互联"),
    ("301531", "33", "春光集团"),
    ("600818", "22", "ST中路"),
    ("603228", "17", "景旺电子"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

KLINE_URL = "https://quota-h.10jqka.com.cn/fuyao/common_hq_aggr/quote/v1/single_kline"
KLINE_AUTH = ("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdXRob3JpemVyX25hbWVzcGFjZSI6ImNvbW1vbi1ocS1hZ2dy"
              "IiwibGljZW5zZWVfdHlwZSI6IkZST05UX0FQUCIsImxpY2Vuc2VlX25hbWVzcGFjZSI6Imh4a2xpbmUtTkVXU19h"
              "cHBOZXdzRmxvd0hvbWVfUGFnZSJ9.ldrvWTheNnGOa_rH_buA6OoUpLtW2bhcdr3fABrGHbk")
KLINE_HEADERS = [
    "x-fuyao-auth: " + KLINE_AUTH,
    "x-auth-progid: 7047",
    "x-auth-type: ths",
    "x-auth-version: 1.0",
    "x-auth-appname: AINVEST",
    "source-id: hxkline-NEWS_appNewsFlowHome_Page",
    "platform: hxkline",
]

# 当日数据结算保护截止：交易日 15:15 之前，当日K线为"形成中" bar，资金为盘中值，不采集
SETTLE_HOUR, SETTLE_MINUTE = 15, 15


def now_cst():
    return datetime.now(CST)


def log(msg):
    line = "[%s] %s" % (now_cst().strftime("%F %T"), msg)
    print(line, flush=True)
    try:
        with open(COLLECT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def curl(url, extra=None, post=None, retries=3):
    """带重试的 HTTP 请求；返回 body 文本，失败返回空串。"""
    for attempt in range(1, retries + 1):
        cmd = ["curl", "-s", "--max-time", "20", "-A", UA]
        for h in (extra or []):
            cmd += ["-H", h]
        if post is not None:
            cmd += ["-X", "POST", "--data-binary", post, "-H", "content-type: application/json"]
        cmd.append(url)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=40).stdout
        except Exception as e:
            r = ""
            log("请求异常(第%d次) %s: %s" % (attempt, url[:60], e))
        if r and not r.lstrip().startswith("<"):
            return r
        log("请求失败(第%d次): %s -> %r" % (attempt, url[:70], (r or "")[:70]))
        time.sleep(3)
    return ""


def fetch_funds(code, mid):
    """资金快照：返回 largeOrderFlow dict 或 None。"""
    url = ("https://stockpage.10jqka.com.cn/stock_page/api/v1/stockpage/funds/"
           "?code=%s&marketId=%s" % (code, mid))
    raw = curl(url, extra=["Referer: https://stockpage.10jqka.com.cn/%s/funds/" % code])
    try:
        d = json.loads(raw)
        if d.get("status_code") == 0:
            return d["data"]["fundsData"]["largeOrderFlow"]
        log("funds 接口返回异常 %s: %s" % (code, raw[:100]))
    except Exception as e:
        log("funds 解析失败 %s: %s raw=%r" % (code, e, raw[:100]))
    return None


def fetch_last_bar(code, mid):
    """K线最近一根日线：返回 {date, close, vol_gu, amt_yuan} 或 None。"""
    body = json.dumps({
        "code_list": [{"codes": [code], "market": mid}],
        "trade_class": "intraday", "time_period": "day_1",
        "trade_date": -1, "begin_time": -1, "end_time": 0,
        "adjust_type": "forward", "gpid": 1,
    })
    raw = curl(KLINE_URL, extra=KLINE_HEADERS, post=body)
    try:
        d = json.loads(raw)
        q = d["data"]["quote_data"][0]
        v = q["value"][-1]
        # data_fields: 1=时间ms 7=开 8=高 9=低 11=收 13=成交量(股) 19=成交额(元)
        return {
            "date": datetime.fromtimestamp(v[0] / 1000, tz=CST).strftime("%F"),
            "close": v[4], "vol_gu": v[5], "amt_yuan": v[6],
        }
    except Exception as e:
        log("kline 解析失败 %s: %s raw=%r" % (code, e, raw[:100]))
        return None


def infer_trade_date_fallback():
    """K线不可用时的粗略推断（不识别节假日）。"""
    now = now_cst()
    d = now.date()
    if d.weekday() < 5 and now.hour < 9:
        d -= timedelta(days=1)  # 盘前持有的是上一交易日
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%F")


def load_ledger():
    """读取账本 -> {(code, trade_date): (mass, big, medium, small)}（同日多行取最后）"""
    existing = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                existing[(r["code"], r["trade_date"])] = (
                    r.get("mass_net"), r.get("big_net"),
                    r.get("medium_net"), r.get("small_net"))
            except Exception:
                continue
    return existing


def ledger_records():
    """读取账本 -> {(code, trade_date): 完整记录dict}（同日多行取最后）"""
    best = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                best[(r["code"], r["trade_date"])] = r
            except Exception:
                continue
    return best


def latest_trade_date():
    """K线权威口径的最近已收盘交易日；失败返回 None。"""
    for code, mid, _name in STOCKS:
        b = fetch_last_bar(code, mid)
        if b:
            return b["date"]
    return None


def _settled(trade_date):
    """该交易日的数据是否已收盘结算（15:15 之后才算当日结算）。"""
    now = now_cst()
    if trade_date != now.strftime("%F"):
        return True  # 不是今天，必然是已结算的历史交易日
    cutoff = now.replace(hour=SETTLE_HOUR, minute=SETTLE_MINUTE,
                         second=0, microsecond=0)
    return now >= cutoff


def collect_decision():
    """判断此刻是否应该采集。返回 (should, reason, last_date)。"""
    last = latest_trade_date()
    if not last:
        last = infer_trade_date_fallback()
    missing = [c for c, _m, _n in STOCKS if (c, last) not in load_ledger()]
    if not missing:
        return False, "最近交易日 %s 已全部入账" % last, last
    if not _settled(last):
        return False, "当日 %s 数据未结算（%02d:%02d 后自动采集）" % (
            last, SETTLE_HOUR, SETTLE_MINUTE), last
    return True, "缺少 %s 的数据（%d只）" % (last, len(missing)), last


def collect_once():
    """完整采集一次（幂等：按 code+trade_date+数据指纹去重）。

    返回摘要 dict: {ok, trade_date, new, dup, fail, summary[]}
    """
    DIR.mkdir(parents=True, exist_ok=True)
    existing = load_ledger()

    # 1) K线确定最近已收盘交易日 + 当日收盘/量额
    bars, trade_date = {}, None
    for code, mid, _name in STOCKS:
        b = fetch_last_bar(code, mid)
        if b:
            bars[code] = b
            trade_date = b["date"]
        time.sleep(1.0)
    date_source = "kline"
    if not trade_date:
        trade_date = infer_trade_date_fallback()
        date_source = "fallback"
        log("警告: K线不可用，交易日按时间规则推断 -> %s（不识别节假日）" % trade_date)
    log("最近已收盘交易日: %s (source=%s)" % (trade_date, date_source))

    # 2) 资金快照采集 + 去重入账
    new_cnt = dup_cnt = fail_cnt = 0
    summary = []
    for code, mid, name in STOCKS:
        f = fetch_funds(code, mid)
        time.sleep(1.5)
        if not f:
            fail_cnt += 1
            log("%s %s 资金快照获取失败" % (code, name))
            continue
        mass = f.get("mass_capital_net_inflow")
        big = f.get("big_capital_net_inflow")
        med = f.get("medium_capital_net_inflow")
        small = f.get("small_capital_net_inflow")
        if not any([mass, big, med, small]):
            log("%s %s 快照全零，疑似盘前清零，跳过不记录" % (code, name))
            continue
        main_net = (mass or 0) + (big or 0)
        fp = (mass, big, med, small)
        key = (code, trade_date)
        note = ""
        if key in existing:
            if existing[key] == fp:
                dup_cnt += 1
                log("%s %s %s 已入账且一致，跳过" % (code, name, trade_date))
                continue
            note = "same_date_diff_values"
            log("警告: %s %s 已有记录但数值不同，追加新行待复核" % (code, name))
        rec = {
            "collected_at": now_cst().strftime("%F %T"),
            "trade_date": trade_date,
            "date_source": date_source,
            "code": code, "name": name, "marketId": mid,
            "caliber": "ths",
            "mass_net": mass, "big_net": big,
            "medium_net": med, "small_net": small,
            "main_net": main_net,
            "close": bars.get(code, {}).get("close"),
            "vol_gu": bars.get(code, {}).get("vol_gu"),
            "amt_yuan": bars.get(code, {}).get("amt_yuan"),
        }
        if note:
            rec["note"] = note
        with open(LEDGER, "a", encoding="utf-8") as fp_out:
            fp_out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        existing[key] = fp
        new_cnt += 1
        summary.append("%s %+.2f万" % (name, main_net / 1e4))

    log("本次采集完成: 新增%d 重复%d 失败%d" % (new_cnt, dup_cnt, fail_cnt))
    if summary:
        log("主力净流入汇总: " + " | ".join(summary))
    return {"ok": fail_cnt == 0 and new_cnt + dup_cnt > 0,
            "trade_date": trade_date, "new": new_cnt,
            "dup": dup_cnt, "fail": fail_cnt, "summary": summary}
