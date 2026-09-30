#!/usr/bin/env bash
# TOOLS-008 负责人手动实测：关闭沙箱与审批启动 Codex，验证仅靠仓库级钩子也能拦下推 main。
set -euo pipefail

usage() {
    cat <<'EOF'
用法：scripts/agent-hooks/manual-codex-no-sandbox.sh [--ref <git ref>] [--out <存档文件>] [--keep]

只供负责人本人在终端手动运行（stdin 不是终端时拒绝运行并退出 1），运行前要求输入 yes 确认。

流程与 live-test.sh codex 相同：在 ${TMPDIR:-/tmp} 下建空 bare 仓库与本仓库指定 ref 的临时克隆
（检出任务分支，本地另有 main，origin 指向 bare），然后以
  codex exec --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust
启动 Codex（不设沙箱、不走审批），要求它只执行 `git push origin main`。沙箱关闭后能挡住推送的只剩
仓库级 .codex/hooks.json → .claude/hooks/guard_bash.py，这正是要验证的。

风险：Codex 在本次运行中拥有你的全部用户权限且不经审批。克隆的 origin 只指向临时 bare 仓库，
提示词要求只执行一条命令，但模型行为不受保证；请在运行期间留意终端输出，必要时 Ctrl-C。

选项：
  --ref <git ref>   被测提交，默认 HEAD（只测已提交内容）。
  --out <文件>      存档文件，默认 docs/实测/TOOLS-008/codex-no-sandbox-<时间戳>.log。
  --keep            结束后保留临时目录。
  -h, --help        显示本说明。

退出码：候选成功返回 3，需人工核验本次运行时事件；失败返回 1（含拒绝运行）；用法错误 2。
EOF
}

ref=HEAD
out=""
keep=0
while [ $# -gt 0 ]; do
    case "$1" in
        -h | --help)
            usage
            exit 0
            ;;
        --ref)
            [ $# -ge 2 ] || { usage >&2; exit 2; }
            ref=$2
            shift 2
            ;;
        --out)
            [ $# -ge 2 ] || { usage >&2; exit 2; }
            out=$2
            shift 2
            ;;
        --keep)
            keep=1
            shift
            ;;
        *)
            echo "未知参数：$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ ! -t 0 ]; then
    echo "拒绝运行：本脚本会关闭 Codex 的沙箱与审批，只能由负责人在交互式终端里手动运行。" >&2
    exit 1
fi
echo "即将以 --dangerously-bypass-approvals-and-sandbox 启动 Codex（无沙箱、无审批）。"
printf '确认继续请输入 yes：'
read -r answer
if [ "$answer" != yes ]; then
    echo "已取消。"
    exit 1
fi

# shellcheck source=scripts/agent-hooks/lib-livetest.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/lib-livetest.sh"

livetest_prepare codex "$ref"
cleanup() {
    if [ "$keep" -eq 1 ]; then echo "保留临时目录：$WORK"; else rm -rf "$WORK"; fi
}
trap cleanup EXIT

livetest_open_log "${out:-$(livetest_default_out codex-no-sandbox)}"

# 钩子信任与项目信任的处理同 live-test.sh codex：临时路径未经 /hooks 信任，用 --dangerously-bypass-hook-trust；
# 用 -c 覆盖 projects 表让项目级 .codex/ 加载（只对本次调用有效）。
trust="\"$CLONE\"={trust_level=\"trusted\"}"
logical="${TMPDIR:-/tmp}"
logical="${logical%/}/${WORK##*/}/clone"
if [ "$logical" != "$CLONE" ]; then trust="$trust,\"$logical\"={trust_level=\"trusted\"}"; fi
AGENT_CMD=(codex exec
    --dangerously-bypass-approvals-and-sandbox
    -C "$CLONE"
    --dangerously-bypass-hook-trust
    -c "projects={$trust}"
    "$LIVETEST_PROMPT")
livetest_header codex --version

echo "临时克隆：$CLONE"
echo "正在运行 codex（无沙箱，输出同时写入 ${OUT}）……"
livetest_run
livetest_conclude
