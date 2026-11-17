#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:-$SCRIPT_DIR/starter_promptfooconfig.yaml}"

echo "[S1-M01] 使用配置文件执行批处理回归对照: $CONFIG_FILE"

if command -v npx >/dev/null 2>&1 && [[ "${AID_FORCE_MOCK:-0}" != "1" ]] && [[ -n "${OPENAI_API_KEY:-}" ]]; then
  npx promptfoo@latest eval -c "$CONFIG_FILE" -o "$SCRIPT_DIR/.last_eval_results.json"
  echo "[S1-M01] promptfoo 评测完成，结果已保存至 .last_eval_results.json（可运行 npx promptfoo@latest view 查看对比矩阵）"
else
  echo "[S1-M01] 当前未启用在线 promptfoo CLI，自动切换本地回归验收器复跑全量对照..."
  python3 "$SCRIPT_DIR/verify.py"
fi
