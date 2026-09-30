#!/usr/bin/env bash
# TOOLS-008 实测：让真实的 Hermes / Codex 会话尝试 `git push origin main`，验证共用守卫能拦下。
set -euo pipefail

usage() {
    cat <<'EOF'
用法：scripts/agent-hooks/live-test.sh <hermes|codex> [--ref <git ref>] [--out <存档文件>] [--keep]

在 ${TMPDIR:-/tmp} 下建临时目录：一个空的 bare 仓库作远端，一个本仓库指定 ref 的克隆
（检出在任务分支上，另有指向同一提交的本地 main，origin 指向该 bare 仓库）。然后在克隆里
非交互启动 agent，要求它只执行 `git push origin main`，被拦截就原样报告。

  hermes  使用调用者已配置的 provider/model，限制 toolsets=file,terminal,todo，
          加 --yolo，用 hermes chat -q（会消耗该配置的额度）
          单次运行；不加 --accept-hooks，所以 ~/.hermes/shell-hooks-allowlist.json 必须已放行守卫命令。
  codex   codex exec --sandbox workspace-write，bare 仓库用 --add-dir 放进可写范围（排除沙箱本身拦截），
          加 --dangerously-bypass-hook-trust 并把临时克隆临时设为 trusted 项目，让仓库级 .codex/hooks.json 生效。

选项：
  --ref <git ref>   被测提交，默认 HEAD。只测已提交的内容，工作区未提交改动不会进入克隆。
  --out <文件>      存档文件，默认 docs/实测/TOOLS-008/<agent>-<时间戳>.log（相对本仓库根）。
  --keep            结束后保留临时目录（默认删除）。
  --no-bypass-hook-trust  Codex 对照实验：不免除钩子信任要求。
  -h, --help        显示本说明。

存档内容：完整命令行、工具版本、agent 全部输出、`git --git-dir=<bare> for-each-ref | wc -l` 的结果。
退出码：agent 正常退出、bare 为 0 且出现守卫标签时返回 3（待人工核验运行时事件）；否则 1；用法错误 2。
注意：会真实调用模型（消耗额度）。
EOF
}

agent=""
ref=HEAD
out=""
keep=0
bypass_trust=1
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
        --no-bypass-hook-trust)
            # 对照实验：codex 不加 --dangerously-bypass-hook-trust，看未信任钩子是否被跳过。
            bypass_trust=0
            shift
            ;;
        hermes | codex)
            [ -z "$agent" ] || { usage >&2; exit 2; }
            agent=$1
            shift
            ;;
        *)
            echo "未知参数：$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done
[ -n "$agent" ] || { usage >&2; exit 2; }

# shellcheck source=scripts/agent-hooks/lib-livetest.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/lib-livetest.sh"

livetest_prepare "$agent" "$ref"
cleanup() {
    if [ "$keep" -eq 1 ]; then echo "保留临时目录：$WORK"; else rm -rf "$WORK"; fi
}
trap cleanup EXIT

out_label=$agent
if [ "$bypass_trust" -eq 0 ]; then out_label="${agent}-no-bypass"; fi
livetest_open_log "${out:-$(livetest_default_out "$out_label")}"

case "$agent" in
    hermes)
        if ! grep -qsF 'guard_bash.py' "${HERMES_HOME:-$HOME/.hermes}/config.yaml"; then
            echo "警告：Hermes config.yaml 里没找到守卫钩子，按 docs/agent拦截钩子.md 安装后再测。" >&2
        fi
        if ! grep -qsF 'guard_bash.py' "${HERMES_HOME:-$HOME/.hermes}/shell-hooks-allowlist.json"; then
            echo "警告：shell-hooks-allowlist.json 里没找到守卫命令，非 TTY 运行时钩子会被跳过。" >&2
        fi
        # 与 studio/bin/app-hermes 相同的模型与工具集参数，外加 --yolo（关掉危险命令审批，只剩钩子把关）。
        # --oneshot + stdin 为 /dev/null：单次回答后退出，且走非 TTY 分支，未在 allowlist 中的钩子不会弹窗而是被跳过。
        # 不加 --accept-hooks：要验证 allowlist 本身生效。--in 让 Hermes 进程 cwd 落在克隆里（钩子靠它定位守卫）。
        AGENT_CMD=(hermes chat
            --toolsets file,terminal,todo
            --in "$CLONE"
            --yolo
            --oneshot
            -q "$LIVETEST_PROMPT")
        livetest_header hermes --version
        ;;
    codex)
        # 临时克隆的路径从未在交互式 codex 的 /hooks 里审阅信任过（信任按 hooks.json 绝对路径+事件+序号记录），
        # 不加 --dangerously-bypass-hook-trust 时 codex exec 会跳过该钩子。此参数只免除本次调用的钩子信任检查，
        # 不关闭沙箱，也不关闭审批。
        # 项目级 .codex/ 只在项目 trusted 时加载：用 -c 覆盖 projects 表（值按 TOML 行内表解析，路径作带引号的键，
        # 不受路径里 . 的影响），只对本次调用有效。逻辑路径与物理路径都登记。
        trust="\"$CLONE\"={trust_level=\"trusted\"}"
        logical="${TMPDIR:-/tmp}"
        logical="${logical%/}/${WORK##*/}/clone"
        if [ "$logical" != "$CLONE" ]; then trust="$trust,\"$logical\"={trust_level=\"trusted\"}"; fi
        AGENT_CMD=(codex exec
            --sandbox workspace-write
            -C "$CLONE"
            --add-dir "$BARE"
            -c "projects={$trust}")
        if [ "$bypass_trust" -eq 1 ]; then AGENT_CMD+=(--dangerously-bypass-hook-trust); fi
        AGENT_CMD+=("$LIVETEST_PROMPT")
        livetest_header codex --version
        ;;
esac

echo "临时克隆：$CLONE"
echo "正在运行 ${agent}（输出同时写入 ${OUT}）……"
livetest_run
livetest_conclude
