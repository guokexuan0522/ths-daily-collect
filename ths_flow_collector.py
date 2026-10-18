#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同花顺口径资金流一次性采集器（手动/调试用）。

平时不需要手动运行——守护进程 ths_supervisor.py 会按需自动采集。
本脚本保留为：手动立即采集一次、或排查问题时使用。
用法: python3 ths_flow_collector.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ths_common as C

if __name__ == "__main__":
    r = C.collect_once()
    print("摘要:", r)
    sys.exit(0 if r.get("ok") else 1)
