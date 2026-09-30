// Conventional Commits；额外允许 wip 供中间提交使用（合并前应 squash 掉）。
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      ["build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor", "revert", "style", "test", "wip"],
    ],
    // 中文描述不受大小写规则约束；英文仍按 config-conventional 默认。
    "header-max-length": [2, "always", 100],
  },
};
