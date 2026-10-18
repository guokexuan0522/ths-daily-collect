#!/usr/bin/env bash
# 同花顺资金流守护进程启动器 —— 由 shell 启动钩子（.zshenv/.bashrc/.profile）调用
# 约束：轻量、幂等、静默；任何情况下都不能影响 shell 正常启动
DIR=/workspace/ths_daily
SUP="$DIR/ths_supervisor.py"
LOCK="$DIR/guard.flock"

# 守护脚本不存在（如挂载异常）则安静退出
[ -f "$SUP" ] || exit 0

# 原子判断：锁被持有 = 守护进程在跑（flock 随进程退出自动释放，无误判无僵锁）
if ! flock -n "$LOCK" -c true 2>/dev/null; then
  exit 0
fi

mkdir -p "$DIR" 2>/dev/null || exit 0

# setsid 脱离当前会话，shell 退出不影响；stdout 由守护进程自行写 supervisor.log
setsid nohup python3 "$SUP" >/dev/null 2>&1 &
exit 0
