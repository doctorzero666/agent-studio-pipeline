#!/usr/bin/env bash
# 包装 gitleaks：它在内部 git 调用失败时仍会打印 "no leaks found" 并以 0 退出
# （本机曾因 x86_64 版 gitleaks 调用 /usr/bin/git 失败而扫描 0 字节）。
# 这里把任何 ERR 日志视为失败，避免把"没扫到"当成"没泄漏"。
set -uo pipefail
out="$(gitleaks "$@" 2>&1)"
rc=$?
printf '%s\n' "$out"
if [ "$rc" -ne 0 ]; then
    exit "$rc"
fi
if printf '%s\n' "$out" | grep -q 'ERR'; then
    echo "run-gitleaks: gitleaks 执行出错，结果不可信，按失败处理。" >&2
    exit 1
fi
