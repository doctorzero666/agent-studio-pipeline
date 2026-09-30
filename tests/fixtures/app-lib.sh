# shellcheck shell=sh
# app-claude / app-codex / app-hermes 共用逻辑，由它们 source，不直接运行。
# 用法：bin/app-<agent> [--dry-run] [--takeover] <app> <任务ID> [-- agent 额外参数...]
# --dry-run、--takeover 在 `--` 之前的任何位置都被识别；`--` 之后的参数原样透传给 agent。
# 调用方逐个取参数交给 app_take_arg，KEEP=1 的参数重新追加到 "$@" 末尾作为透传参数；
# 然后调用 app_prepare：设置 APP_DIR、TASK_CARD、WORKTREE、BRANCH、EXECUTOR，非 dry-run 时确保 worktree 存在。

app_die() {
    printf 'app-%s：%s\n' "$AGENT" "$1" >&2
    exit "${2:-1}"
}

app_usage() {
    printf '用法：bin/app-%s [--dry-run] [--takeover] <app> <任务ID> [-- %s 额外参数...]\n' "$AGENT" "$AGENT" >&2
    exit 2
}

# 处理一个参数：识别启动器选项与两个位置参数；KEEP=1 表示该参数透传给 agent。
APP=''
TASK_ID=''
DRY_RUN=0
TAKEOVER=0
APP_SEEN_DD=0
app_take_arg() {
    KEEP=0
    if [ "$APP_SEEN_DD" -eq 1 ]; then
        KEEP=1
        return 0
    fi
    case "$1" in
        --) APP_SEEN_DD=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --takeover) TAKEOVER=1 ;;
        --dry-run*|--takeover*) app_die "无法识别的选项：$1" 2 ;;
        -h|--help) app_usage ;;
        -*)
            if [ -z "$APP" ] || [ -z "$TASK_ID" ]; then
                app_die "未知选项：${1}。给 agent 的参数请放在 -- 之后" 2
            fi
            KEEP=1 ;;
        *)
            if [ -z "$APP" ]; then APP=$1
            elif [ -z "$TASK_ID" ]; then TASK_ID=$1
            else KEEP=1
            fi ;;
    esac
}

# 读取任务卡"当前执行者"字段；缺失时返回非 0。
app_read_executor() {
    line=$(grep -m1 -E '^\| 当前执行者 \|' "$1") || return 1
    printf '%s\n' "$line" | sed -E 's/^\| 当前执行者 \|[[:space:]]*//; s/[[:space:]]*\|[[:space:]]*$//'
}

# 参数处理完后调用：核对任务卡与执行者，打印信息，按需创建 worktree。
app_prepare() {
    case "$APP" in
        ''|*/*|.|..|.*) app_die "应用名不合法：$APP" 2 ;;
    esac
    [ -n "$APP" ] && [ -n "$TASK_ID" ] || app_usage
    printf '%s\n' "$TASK_ID" | LC_ALL=C grep -Eq '^[A-Z][A-Z0-9]*-[0-9]{3,}$' ||
        app_die "任务编号格式不合法：${TASK_ID}（应为大写字母前缀-三位以上数字，如 TOOLS-001）" 2

    STUDIO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
    WORKSPACE_ROOT=$(dirname -- "$STUDIO_ROOT")
    APP_DIR="$WORKSPACE_ROOT/$APP"
    TASK_CARD="$STUDIO_ROOT/项目/应用/$APP/tasks/$TASK_ID/task.md"
    WORKTREE="$APP_DIR/.claude/worktrees/$TASK_ID"
    BRANCH="agent/$AGENT/$TASK_ID"

    [ -d "$APP_DIR" ] || app_die "找不到应用目录：$APP_DIR"
    top=$(git -C "$APP_DIR" rev-parse --show-toplevel 2>/dev/null) || app_die "不是 git 仓库：$APP_DIR"
    [ "$(cd "$top" && pwd -P)" = "$(cd "$APP_DIR" && pwd -P)" ] ||
        app_die "$APP_DIR 不是独立 git 仓库的根目录（git 根为 ${top}）"
    [ -f "$TASK_CARD" ] || app_die "找不到任务卡：$TASK_CARD"

    EXECUTOR=$(app_read_executor "$TASK_CARD") || app_die "任务卡缺少\"| 当前执行者 |\"字段：$TASK_CARD"
    case "$EXECUTOR" in
        ''|'无'|'无（'*|'无('*|'无；'*|'无;'*|'无，'*|'无,'*|'无 '*) occupied=0 ;;
        *) occupied=1 ;;
    esac

    if [ -d "$WORKTREE" ]; then
        wt_state="已存在"
        wt_branch=$(git -C "$WORKTREE" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "（分离 HEAD 或非 worktree）")
    elif git -C "$APP_DIR" rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null; then
        wt_state="待创建（检出已有分支 ${BRANCH}）"
        wt_branch=$BRANCH
    else
        wt_state="待创建（从本地 main 新建分支 ${BRANCH}）"
        wt_branch=$BRANCH
    fi

    printf '应用仓库：%s\n' "$APP_DIR"
    printf 'worktree：%s（%s）\n' "$WORKTREE" "$wt_state"
    printf '分支：%s\n' "$wt_branch"
    printf '任务卡：%s\n' "$TASK_CARD"
    printf '当前执行者：%s\n' "${EXECUTOR:-（空）}"

    if [ "$occupied" -eq 1 ]; then
        if [ "$TAKEOVER" -eq 1 ]; then
            printf '警告：任务卡已有执行者，因 --takeover 继续。接手后先核对实际文件与状态，再在任务卡改写执行者。\n' >&2
        else
            app_die "任务卡已有执行者，拒绝启动。确认原执行者已中断后，用 --takeover 接手。" 3
        fi
    fi
    if [ -d "$WORKTREE" ] && [ "$wt_branch" != "$BRANCH" ]; then
        printf '警告：已有 worktree 的分支是 %s，不是约定的 %s。\n' "$wt_branch" "$BRANCH" >&2
    fi
    if ! git -C "$APP_DIR" check-ignore -q ".claude/worktrees/$TASK_ID"; then
        printf '警告：%s 的 .gitignore 未忽略 .claude/worktrees/，请在应用仓库补上。\n' "$APP" >&2
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'dry-run：只打印，不创建 worktree，不启动 %s。\n' "$AGENT"
        exit 0
    fi

    if [ ! -d "$WORKTREE" ]; then
        if git -C "$APP_DIR" rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null; then
            git -C "$APP_DIR" worktree add "$WORKTREE" "$BRANCH" >&2 || app_die "创建 worktree 失败"
        else
            git -C "$APP_DIR" rev-parse --verify --quiet refs/heads/main >/dev/null ||
                app_die "$APP 没有本地 main 分支，无法创建 worktree"
            git -C "$APP_DIR" worktree add -b "$BRANCH" "$WORKTREE" main >&2 || app_die "创建 worktree 失败"
        fi
    fi
}
