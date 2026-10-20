# -*- coding: utf-8 -*-
"""
GitHub Actions 采集入口（云端定时执行，无需本地 VM 在线）

由 .github/workflows/collect.yml 按 cron 调用（北京时间 08:30 / 15:45 / 18:00）。
逻辑与本地守护进程共用 ths_common.collect_once()：
  - 采集 4 只股票同花顺口径主力资金流，写入 flows.jsonl
  - 渲染自包含 dashboard.html
  - 追加 runs.log 运行痕迹
  - 有新增数据时自动 commit + push 回仓库（本地守护进程定时 pull 拉回）
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ths_common as C


def sh(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def main():
    r = C.collect_once()
    C.log("[actions] collect_once -> ok=%s trade_date=%s new=%s dup=%s fail=%s"
          % (r.get("ok"), r.get("trade_date"), r.get("new"),
             r.get("dup"), r.get("fail")))

    # 记录运行痕迹（union merge 防冲突）
    with open(C.DIR / "runs.log", "a", encoding="utf-8") as f:
        f.write("[%s] ok=%s date=%s new=%s dup=%s fail=%s\n"
                % (C.now_cst().strftime("%F %T"), r.get("ok"),
                   r.get("trade_date"), r.get("new"), r.get("dup"),
                   r.get("fail")))

    # 渲染看板 + 持仓页（含选股候选池板块）
    try:
        import render_dashboard
        render_dashboard.render()
        import pos_watch
        pos_watch.render()
    except Exception as e:
        C.log("[actions] render failed: %r" % e)

    # 每日选股（收盘后15:45起运行一次，当天不重复；盘中守卫同源）
    try:
        import selector
        if C._intraday_block():
            C.log("[actions] 盘中守卫: 跳过每日选股（15:45后运行）")
        else:
            import json as _json
            pj = C.DIR / "picks.json"
            today = C.now_cst().strftime("%F")
            done = False
            if pj.exists():
                try:
                    done = _json.loads(pj.read_text(encoding="utf-8")).get(
                        "generated_at", "")[:10] == today
                except Exception:
                    pass
            if done:
                C.log("[actions] 今日选股已生成，跳过")
            else:
                selector.run(pool_limit=500)
                import pos_watch
                pos_watch.render()
    except Exception as e:
        C.log("[actions] selector failed: %r" % e)

    if not r.get("ok"):
        # 采集失败不阻断 workflow，退出码 0（cron 下次会重试）
        C.log("[actions] 采集失败，下次 cron 重试")
        return 0

    if not (C.DIR / ".git").exists():
        return 0

    # 云端运行时使用内置 GITHUB_TOKEN 推送；本地运行时沿用已配置的远端
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        sh(["git", "remote", "set-url", "origin",
            "https://x-access-token:%s@github.com/guokexuan0522/ths-daily-collect.git" % tok])

    sh(["git", "config", "user.name", "ths-bot"])
    sh(["git", "config", "user.email", "ths-bot@users.noreply.github.com"])
    sh(["git", "add", "flows.jsonl", "runs.log", "dashboard.html", "index.html", "position.html", "flows.html", "picks.json"])
    d = sh(["git", "diff", "--cached", "--quiet"])
    if d.returncode != 0:
        c = sh(["git", "commit", "-m", "collect %s" % r.get("trade_date")])
        C.log("[actions] commit rc=%s %s" % (c.returncode, (c.stdout or "").strip()[:120]))
        p = sh(["git", "push"])
        if p.returncode != 0:
            # 推送被拒（并发写入），拉取合并后再推
            sh(["git", "pull", "--no-edit", "--no-rebase"])
            p = sh(["git", "push"])
            C.log("[actions] push rc=%s %s" % (p.returncode, (p.stderr or "").strip()[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
