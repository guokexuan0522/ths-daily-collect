# -*- coding: utf-8 -*-
"""
同花顺资金流守护进程（常驻 + 自愈 + 智能采集时机）

设计目标（针对"定时任务派发不执行"根因的彻底重构）：
  - 不依赖平台调度器派发 agent 会话（实测不可靠：VM 不在线时派发只记录不执行）
  - 由 shell 启动钩子（.zshenv/.bashrc/.profile）在每次会话/Shell 启动时拉起
  - 内部每 10 分钟扫描一次，智能判断采集时机：
      * 最近交易日数据缺失 且 该日已收盘结算(当日15:15后) -> 立即采集
      * 非交易日/周末 -> 接口仍持有最近交易日数据，可随时补采
      * 当日盘中(9:15-15:15) -> 不采集（数据未结算，避免记入盘中值）
  - 单实例保护：flock 锁文件，进程崩溃自动释放；重复启动自动退出
  - 心跳写入 guard.status.json，供随时核查存活与最近决策
"""
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ths_common as C

DIR = C.DIR
STATUS = DIR / "guard.status.json"
SUP_LOG = DIR / "supervisor.log"
SCAN_INTERVAL = 600  # 秒
GIT_SYNC_EVERY = 3   # 每3轮(30分钟)做一次仓库同步


def _now():
    return datetime.now(C.CST).strftime("%F %T")


def slog(msg):
    line = "[%s] %s" % (_now(), msg)
    try:
        with open(SUP_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def write_status(**kw):
    st = {}
    try:
        if STATUS.exists():
            st = json.loads(STATUS.read_text(encoding="utf-8"))
            if not isinstance(st, dict):
                st = {}
    except Exception:
        st = {}
    st.update(kw)
    st["pid"] = os.getpid()
    st["now"] = _now()
    st["alive"] = True
    tmp = STATUS.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(STATUS)
    except Exception as e:
        slog("状态写入失败: %r" % e)


def refresh_dashboard():
    try:
        import render_dashboard
        render_dashboard.render()
    except Exception as e:
        slog("看板刷新失败: %r" % e)


def _git(args):
    return subprocess.run(["git", "-C", str(DIR)] + args,
                          capture_output=True, text=True, timeout=120)


def git_sync():
    """采集数据与 git 远端互相同步（GitHub Actions 侧写入的新数据拉回本地）。

    仅当目录已初始化为 git 仓库时执行；任何失败都只记录不中断主循环。
    """
    if not (DIR / ".git").exists():
        return "no-repo"
    try:
        _git(["add", "-A"])
        r = _git(["diff", "--cached", "--quiet"])
        if r.returncode != 0:
            c = _git(["commit", "-m", "data: collect %s" % _now()])
            if c.returncode != 0:
                slog("git commit 失败: %s" % (c.stderr or "").strip()[:200])
        pl = _git(["remote"])
        if not (pl.stdout or "").strip():
            return "no-remote"
        pl = _git(["pull", "--no-edit", "--no-rebase"])
        if pl.returncode != 0:
            slog("git pull 失败: %s" % (pl.stderr or "").strip()[:200])
        for _ in range(2):
            ps = _git(["push"])
            if ps.returncode == 0:
                return "ok"
            # 推送被拒多为远端有新提交，拉取合并后再推
            _git(["pull", "--no-edit", "--no-rebase"])
        slog("git push 失败: %s" % (ps.stderr or "").strip()[:200])
        return "push-fail"
    except Exception as e:
        slog("git_sync 异常: %r" % e)
        return "error"


def main():
    DIR.mkdir(parents=True, exist_ok=True)

    # 单实例保护：flock 随进程退出自动释放，崩溃后下轮启动可接管
    lock_fd = open(DIR / "guard.flock", "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        slog("另一守护进程已在运行，本次启动退出")
        return 0

    slog("守护进程启动 pid=%d（每%d秒扫描，采集判定: 缺失交易日且已结算）"
         % (os.getpid(), SCAN_INTERVAL))
    write_status(started_at=_now(), consecutive_failures=0)

    fails = 0
    cycle = 0
    while True:
        cycle += 1
        try:
            should, reason, last = C.collect_decision()
            if should:
                slog("采集判定: 执行 | %s" % reason)
                r = C.collect_once()
                ok = bool(r.get("ok"))
                fails = 0 if ok else fails + 1
                write_status(last_collect_at=_now(),
                             last_collect_date=r.get("trade_date"),
                             last_collect_ok=ok,
                             last_collect_new=r.get("new"),
                             last_collect_dup=r.get("dup"),
                             last_collect_fail=r.get("fail"),
                             consecutive_failures=fails)
                if ok:
                    refresh_dashboard()
            else:
                write_status(last_check=_now(), last_reason=reason)
        except Exception as e:
            fails += 1
            slog("本轮异常: %r" % e)
            write_status(last_error=repr(e), consecutive_failures=fails)

        if cycle % GIT_SYNC_EVERY == 0:
            gs = git_sync()
            write_status(last_git_sync=_now(), last_git_sync_result=gs)
            if gs == "ok":
                # Actions 侧可能写入了新数据，刷新看板
                refresh_dashboard()

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
