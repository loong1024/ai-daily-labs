"""AI 日课实战实验仓公共底座（纯 Python 标准库，零强制第三方依赖）。

提供两项核心能力：
1. LabVerifier：支持红绿闭环验收（默认检查 starter.* 给出修复提示；传入 --solution 检查标准参考实现）。
2. chat_complete：三模无缝切换（OpenAI 兼容接口 / 本地 Ollama / 无 Key 确定性离线 Mock）。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.request
from typing import Any, Callable


def load_dotenv_if_present(start_dir: pathlib.Path | None = None) -> None:
  cur = (start_dir or pathlib.Path.cwd()).resolve()
  for folder in [cur, *cur.parents]:
    env_file = folder / ".env"
    if env_file.is_file():
      for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
          continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
      break


def use_solution() -> bool:
  return "--solution" in sys.argv or os.environ.get("AID_VERIFY_SOLUTION") == "1"


def target_file(lab_dir: pathlib.Path, starter_rel: str, solution_rel: str) -> pathlib.Path:
  return lab_dir / (solution_rel if use_solution() else starter_rel)


class LabVerifier:
  """统一的实验量化验收器。"""

  def __init__(self, lab_id: str, title: str) -> None:
    self.lab_id = lab_id
    self.title = title
    self.mode = "SOLUTION 标准参考验收" if use_solution() else "STARTER 当前进度验收"
    self.results: list[tuple[str, bool, str]] = []

  def check(self, name: str, passed: bool, fix_hint: str = "") -> bool:
    self.results.append((name, bool(passed), fix_hint))
    return bool(passed)

  def finish(self) -> int:
    print(f"=== [{self.lab_id}] {self.title} ({self.mode}) ===")
    failed_hints: list[str] = []
    for idx, (name, ok, hint) in enumerate(self.results, 1):
      badge = "✅ PASS" if ok else "❌ FAIL"
      print(f"  {badge} [{idx}/{len(self.results)}] {name}")
      if not ok and hint:
        failed_hints.append(f"  - {name}：{hint}")
    if failed_hints:
      print("\n👉 Vibe Coding 改进提示（可直接发给 AI 助手协助修改 starter 文件）：")
      for h in failed_hints:
        print(h)
      print(f"\n结果：未通过（通过 {sum(1 for _, ok, _ in self.results if ok)}/{len(self.results)} 项）")
      sys.exit(1)
    print(f"\n🎉 PASS [{self.lab_id}] 全部 {len(self.results)} 项验收指标通过！")
    sys.exit(0)


def chat_complete(
    messages: list[dict[str, str]],
    *,
    mock_fn: Callable[[list[dict[str, str]]], str] | None = None,
    temperature: float = 0.0,
    response_json: bool = False,
) -> str:
  """三模自适应大模型调用器：
  1. 若配置 OPENAI_API_KEY（且 AID_FORCE_MOCK != 1），调用 OpenAI 兼容接口；
  2. 若配置 OLLAMA_MODEL（且 AID_FORCE_MOCK != 1），调用本地 Ollama；
  3. 默认回退至确定性离线 mock_fn，确保零 API Key 也能 30 秒验证工程逻辑。
  """
  load_dotenv_if_present()
  if os.environ.get("AID_FORCE_MOCK") != "1":
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key and not api_key.startswith("sk-your-"):
      base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
      model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
      body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
      if response_json:
        body["response_format"] = {"type": "json_object"}
      req = urllib.request.Request(
          f"{base}/chat/completions",
          data=json.dumps(body).encode("utf-8"),
          headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
          method="POST",
      )
      with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

    ollama_model = os.environ.get("OLLAMA_MODEL", "").strip()
    if ollama_model:
      host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
      body = {"model": ollama_model, "messages": messages, "stream": False, "options": {"temperature": temperature}}
      if response_json:
        body["format"] = "json"
      req = urllib.request.Request(
          f"{host}/api/chat",
          data=json.dumps(body).encode("utf-8"),
          headers={"Content-Type": "application/json"},
          method="POST",
      )
      with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        return payload["message"]["content"]

  if mock_fn is not None:
    return mock_fn(messages)
  raise RuntimeError("未配置 OPENAI_API_KEY / OLLAMA_MODEL，且当前调用未提供离线 mock_fn。")
