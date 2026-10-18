#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同花顺口径资金账本汇总器
用法:
  python3 summarize.py                # 汇总账本全部记录
  python3 summarize.py 2026-10-12 2026-10-16   # 汇总指定日期区间
  python3 summarize.py --code 002491  # 只看某只股票
输出: 每股票逐日 主力净额(万)/收盘/成交量(万手)/成交额(亿) + 区间合计
"""
import json
import sys
from pathlib import Path

LEDGER = Path("/workspace/ths_daily/flows.jsonl")
NAMES = {"002491": "通鼎互联", "301531": "春光集团",
         "600818": "ST中路", "603228": "景旺电子"}


def main():
    args = [a for a in sys.argv[1:]]
    code_filter = None
    if "--code" in args:
        i = args.index("--code")
        code_filter = args[i + 1]
        del args[i:i + 2]
    start = args[0] if len(args) >= 1 else "0000-01-01"
    end = args[1] if len(args) >= 2 else "9999-12-31"

    if not LEDGER.exists():
        print("账本不存在:", LEDGER)
        return 1

    # 同一 (code, trade_date) 多条时取最后一条（最新采集）
    best = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        k = (r["code"], r["trade_date"])
        best[k] = r

    codes = [code_filter] if code_filter else sorted(NAMES)
    for code in codes:
        rows = [r for (c, _d), r in sorted(best.items(), key=lambda kv: kv[0][1])
                if c == code and start <= r["trade_date"] <= end]
        if not rows:
            continue
        print("=" * 72)
        print("%s %s（同花顺口径，主力净额 = 超大单净 + 大单净）" % (code, NAMES.get(code, "")))
        print("%-12s %12s %10s %12s %10s" % ("交易日", "主力净额(万)", "收盘", "成交量(万手)", "成交额(亿)"))
        tm = tv = ta = 0.0
        for r in rows:
            tm += r["main_net"] or 0
            tv += (r.get("vol_gu") or 0) / 1e6
            ta += (r.get("amt_yuan") or 0) / 1e8
            close = r.get("close")
            vol = r.get("vol_gu")
            amt = r.get("amt_yuan")
            print("%-12s %12.2f %10s %12.2f %10.2f" % (
                r["trade_date"], (r["main_net"] or 0) / 1e4,
                ("%.2f" % close) if close is not None else "-",
                (vol / 1e6) if vol else 0.0,
                (amt / 1e8) if amt else 0.0))
        print("%-12s %12.2f %10s %12.2f %10.2f" % ("区间合计", tm / 1e4, "-", tv, ta))
    print("=" * 72)
    print("注: 成交量为万手(=10万股)，成交额为亿元；数据采自同花顺官方接口。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
