# -*- coding: utf-8 -*-
"""M3 地基 v2：拉取全市场 500 日历史日K -> history.npz（numpy压缩，本地回测用）。

v2 修复（v1 在对齐步崩溃：共同交易日交集为空——个别股票日期串变异
如无零填充/带空格，一颗坏苹果清空整个交集）：
  1. 日期归一化 canon_date()：兼容 "2024-9-23"/"20240923"/"2024-09-23 00:00:00"
  2. 增量缓存 history_raw.jsonl：逐只追加，中断后可断点续传，不再一崩全丢
  3. 稳健对齐：参考窗口=全市场最近480个交易日；个股覆盖≥99%才入矩阵，
     缺失日（停牌）按前收前向填充、成交量置0——比严格交集更真实且不会崩
  4. 对齐诊断：打印参考窗口/保留数/剔除样例，坏数据可见
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
CACHE = DIR / "history_raw.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://finance.sina.com.cn/"}
N = 500
WINDOW = 480          # 参考窗口：全市场最近480个交易日
MIN_COVER = 0.99      # 个股至少覆盖窗口的99%才入矩阵
MIN_BARS = 420        # 上市未满两年/失败的跳过


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def canon_date(s):
    """日期串归一化为 YYYY-MM-DD（容忍无零填充/时间戳/纯数字）"""
    s = str(s).strip().split(" ")[0].split("T")[0]
    if "-" in s:
        parts = s.split("-")
        if len(parts) == 3:
            return "%04d-%02d-%02d" % (int(parts[0]), int(parts[1]), int(parts[2]))
    if len(s) == 8 and s.isdigit():
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:])
    return s


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


def fetch_one(sym):
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d"
           % (sym, N))
    try:
        data = json.loads(_get(url))
    except Exception:
        return None
    if not isinstance(data, list) or len(data) < MIN_BARS:
        return None
    dates, c, h, l, v = [], [], [], [], []
    for x in data:
        try:
            dates.append(canon_date(x["day"]))
            c.append(float(x["close"]))
            h.append(float(x["high"]))
            l.append(float(x["low"]))
            v.append(float(x["volume"]))
        except Exception:
            return None
    return dates, c, h, l, v


def load_cache():
    """读增量缓存 -> {code: (name, symbol, dates, c, h, l, v)}"""
    out = {}
    if not CACHE.exists():
        return out
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        out[r["code"]] = (r["name"], r["symbol"], r["dates"],
                          r["c"], r["h"], r["l"], r["v"])
    return out


def main():
    t0 = time.time()
    market = fetch_market_codes()
    print("全市场 %d 只，开始拉取 %d 日K（缓存续传）..." % (len(market), N))
    cache = load_cache()
    print("缓存已有 %d 只，需新拉 %d 只" % (len(cache), len(market) - len(cache)))
    ok = fail = 0
    with open(CACHE, "a", encoding="utf-8") as f:
        for i, r in enumerate(market):
            sym, code, name = r["symbol"], r["code"], r["name"]
            if code in cache:
                continue
            rec = fetch_one(sym)
            if rec is None:
                fail += 1
                continue
            dates, c, h, l, v = rec
            f.write(json.dumps({"code": code, "name": name, "symbol": sym,
                                "dates": dates, "c": c, "h": h, "l": l, "v": v},
                               ensure_ascii=False) + "\n")
            f.flush()
            ok += 1
            if ok % 500 == 0:
                print("  新拉 %d 只 失败%d 耗时%.0fs" % (ok, fail, time.time() - t0))
            time.sleep(0.035)
    print("拉取阶段完成：新拉%d 失败%d，耗时%.0fs" % (ok, fail, time.time() - t0))

    # ===== 对齐：参考窗口 + 99%覆盖 + 停牌前向填充 =====
    series = {code: (name, sym, dts, c, h, l, v)
              for code, (name, sym, dts, c, h, l, v) in load_cache().items()}
    print("参与对齐股票 %d 只" % len(series))
    all_dates = sorted({d for _, _, dts, *_ in series.values() for d in dts})
    if not all_dates:
        raise SystemExit("没有任何有效日期，对齐失败")
    window = all_dates[-WINDOW:]
    wset = set(window)
    print("参考窗口: %s ~ %s 共%d个交易日" % (window[0], window[-1], len(window)))

    kept, dropped = {}, []
    for code, (name, sym, dts, c, h, l, v) in series.items():
        dmap = dict(zip(dts, range(len(dts))))
        cover = sum(1 for d in window if d in dmap)
        if cover >= MIN_COVER * len(window):
            kept[code] = (name, sym, dmap, c, h, l, v)
        else:
            dropped.append((code, name, cover))
    print("入矩阵 %d 只，剔除 %d 只（覆盖不足）" % (len(kept), len(dropped)))
    for code, name, cov in dropped[:10]:
        print("  剔除样例: %s %s 覆盖%d/%d" % (code, name, cov, len(window)))

    codes = sorted(kept.keys())
    C = np.zeros((len(codes), len(window)), dtype=np.float32)
    H = np.zeros_like(C); L = np.zeros_like(C); V = np.zeros_like(C)
    for j, code in enumerate(codes):
        name, sym, dmap, c, h, l, v = kept[code]
        last = None
        for t, d in enumerate(window):
            k = dmap.get(d)
            if k is not None:
                last = (c[k], h[k], l[k], v[k])
                C[j, t], H[j, t], L[j, t], V[j, t] = last
            elif last is not None:      # 停牌日：前收前向填充，成交量0
                C[j, t], H[j, t], L[j, t] = last[0], last[1], last[2]
                V[j, t] = 0.0
            else:                       # 窗口前端缺失：用首个可得值
                k0 = min(dmap.values())
                C[j, t], H[j, t], L[j, t], V[j, t] = c[k0], h[k0], l[k0], v[k0]
    names = {code: kept[code][0] for code in codes}
    np.savez_compressed(OUT_NPZ, codes=np.array(codes), dates=np.array(window),
                        C=C, H=H, L=L, V=V)
    OUT_NAMES.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print("已写入 history.npz (%.1fMB) + history_names.json，总耗时%.0fs"
          % (OUT_NPZ.stat().st_size / 1e6, time.time() - t0))


if __name__ == "__main__":
    main()
