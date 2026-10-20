# -*- coding: utf-8 -*-
"""M3 地基：拉取全市场 500 日历史日K -> history.npz（numpy压缩，本地回测用）。

一次拉取，回测复用。不入 git（体积大）。云端回测时重新拉取。
"""
import json
import time
import urllib.request
from pathlib import Path

import numpy as np

DIR = Path(__file__).resolve().parent
OUT_NPZ = DIR / "history.npz"
OUT_NAMES = DIR / "history_names.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://finance.sina.com.cn/"}
N = 500


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def fetch_market_codes():
    rows, page = [], 1
    while page <= 60:
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/"
               "json_v2.php/Market_Center.getHQNodeData?page=%d&num=100"
               "&sort=amount&asc=0&node=hs_a" % page)
        try:
            batch = json.loads(_get(url))
        except Exception as e:
            print("市场列表第%d页失败: %r" % (page, e))
            break
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.15)
    return rows


def main():
    t0 = time.time()
    market = fetch_market_codes()
    print("全市场 %d 只，开始拉取 %d 日K..." % (len(market), N))
    series, names = {}, {}
    ok = fail = 0
    for i, r in enumerate(market):
        sym, code, name = r["symbol"], r["code"], r["name"]
        url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d"
               % (sym, N))
        data = None
        for attempt in range(2):
            try:
                data = json.loads(_get(url))
                break
            except Exception:
                time.sleep(0.5)
        if not data or len(data) < 420:      # 上市未满两年/失败的跳过
            fail += 1
            continue
        dates = [x["day"] for x in data]
        c = np.array([float(x["close"]) for x in data], dtype=np.float32)
        h = np.array([float(x["high"]) for x in data], dtype=np.float32)
        l = np.array([float(x["low"]) for x in data], dtype=np.float32)
        v = np.array([float(x["volume"]) for x in data], dtype=np.float32)
        series[code] = (dates, c, h, l, v)
        names[code] = name
        ok += 1
        if (i + 1) % 500 == 0:
            print("  进度 %d/%d 成功%d 失败%d 耗时%.0fs"
                  % (i + 1, len(market), ok, fail, time.time() - t0))
        time.sleep(0.035)
    # 对齐：取各股票日期集合的交集（约480+个共同交易日）
    common = set(series[list(series.keys())[0]][0])
    for code in series:
        common &= set(series[code][0])
    dates = sorted(common)
    print("共同交易日: %d 天 (%s ~ %s)，覆盖股票 %d 只"
          % (len(dates), dates[0], dates[-1], len(series)))
    idx = {d: k for k, d in enumerate(dates)}
    C = np.zeros((len(series), len(dates)), dtype=np.float32)
    H = np.zeros_like(C)
    L = np.zeros_like(C)
    V = np.zeros_like(C)
    codes = []
    for j, code in enumerate(series):
        dts, c, h, l, v = series[code]
        pos = [idx[d] for d in dts if d in idx]
        C[j, :] = c
        H[j, :] = h
        L[j, :] = l
        V[j, :] = v
        codes.append(code)
    np.savez_compressed(OUT_NPZ, codes=np.array(codes), dates=np.array(dates),
                        C=C, H=H, L=L, V=V)
    OUT_NAMES.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print("已写入 history.npz (%.1fMB) + history_names.json，总耗时%.0fs"
          % (OUT_NPZ.stat().st_size / 1e6, time.time() - t0))


if __name__ == "__main__":
    main()
