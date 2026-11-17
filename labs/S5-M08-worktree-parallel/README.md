# S5-M08 · 双开AI改同目录互相覆盖？git worktree隔离并行实验

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`idea` | **预计耗时**：55 分钟 | **专题**：`vibe_coding`

## 1. 场景痛点：为什么双开 AI 编码会话总是一团乱麻？

手头同时有两个互不干扰的小任务（例如“给订单导出补 CSV 表头”和“修分页器偏移 Bug”），很多开发者直接双开两个 AI 窗口，结果连踩三颗大雷：

1. **同目录互踩抹掉代码**：两个会话共用同一个工作目录，窗口 B 一句 `git checkout` 或回滚重试，瞬间把窗口 A 刚改了一半的代码直接冲掉。
2. **裸建 worktree 跑不起单测**：兴冲冲运行了 `git worktree add ../wt-task1`，却发现兄弟目录里既没有虚拟环境依赖（`.venv` / `node_modules`），也没有 `.env` 测试配置；情急之下把含生产密钥的 `.env` 原样拷过去又造成敏感凭据扩散。
3. **收尾遗留孤儿目录与垃圾分支**：土法复制整个项目文件夹不仅双倍占磁盘，合并完还经常忘记跑 `git worktree remove` 和 `git branch -d`，留下一堆过期的临时目录与悬空分支。

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验任务书、`git worktree` 并行标准操作序列与验收指南 |
| `fixtures/parallel_tasks_spec.json` | 种子项目源码（含锁死在 `main` 的共享契约 `app/contracts.py`）、正交双任务（`feat/export` + `fix/pagination`）及非正交冲突反例 |
| `fixtures/dirty_env_sample.env` | 混合了测试参数与模拟生产敏感项的 `.env` 样本（用于测试最小权限脱敏复制） |
| `starter.py` | **待改进起点**：缺正交预检、原样拷贝脏 `.env`、在同目录硬改且未清理 worktree 的残缺编排器 |
| `solution.py` | **标准参考实现**：完整实现契约预检、`git worktree add` 物理隔离、共享依赖链接、最小化 `.env` 注入、无冲突合入 `main` 与 100% 无痕清理 |
| `verify.py` | 红绿闭环量化验收脚本（在真实临时 Git 仓库中执行 `git worktree` 全生命周期并跑 `unittest` 验证！） |

> **安全纪律提示**：`fixtures/dirty_env_sample.env` 中的敏感项均使用 `FAKE_..._DO_NOT_USE_...` 演练占位符，切勿写入任何真实密钥。

---

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴进 Cursor / Claude Code / Windsurf / Codespaces 对话框即可启动结对闯关：

```text
请阅读 @labs/S5-M08-worktree-parallel/README.md 及 fixtures/，按结对教练协议带我改进 starter.py，运行 python3 labs/S5-M08-worktree-parallel/verify.py 直到全部通过。
```

---

## 4. 55 分钟实操步骤指引

### Step 1：跑通基线验收，观察反模式翻车现场（10 分钟）
运行 `verify.py` 观察未改造的 `starter.py` 暴露出的 4 类问题：

```bash
python3 labs/S5-M08-worktree-parallel/verify.py
```

### Step 2：实现并行前正交性与共享契约锁死预检（10 分钟）
完善 `starter.py` 中的 `check_task_orthogonality(task_a, task_b, locked_contracts)`：
- 检查两个任务的 `target_files` 是否存在交集（若有重叠文件，双线并行合并必冲突）；
- 检查是否擅自修改已锁死在 `main` 分支的共享接口契约文件（如 `app/contracts.py`）；若需改契约，必须先在 `main` 单独提交锁死后再开分支。

### Step 3：创建物理隔离兄弟 Worktree + 补齐共享依赖与最小化 `.env`（20 分钟）
完善 `build_minimal_test_env(raw_env_text)` 与 `run_parallel_worktree_workflow(...)`：
1. **安全最小化 `.env`**：过滤掉所有 `PROD_*`、`PRODUCTION_*`、`*_LIVE_*` 等生产敏感项，保留测试所需配置并强制写入 `APP_ENV=test` 与 `WORKTREE_ISOLATED=1`。
2. **创建共享 Git 历史的隔离目录**：调用 `git worktree add -b <branch> <wt_dir> main` 在兄弟目录建好两个并行工作树（注意观察 `<wt_dir>/.git` 只是一个轻量级指针文件，无需拷贝整仓历史！）。
3. **零重装复用本地依赖**：将 `shared_deps_dir` 软链接到 `<wt_dir>/.venv_shared`，让两个隔离目录各自跑 `unittest` 立即全绿，且全程完全不触碰 `main` 主目录工作区。

### Step 4：审查合入 `main`、跑全量回归并执行 100% 无痕清理（15 分钟）
完善 `run_parallel_worktree_workflow(...)` 的收尾阶段：
1. 两个特性分支各自单测通过并提交后，回到 `main` 依次执行 `git merge --no-ff` 合入两个分支，运行一次全量测试确认 `exporter` + `paginator` + `contracts` 联合全绿；
2. 清理工作树内未跟踪的临时 `.env` 与 `.venv_shared` 链接，依次执行 `git worktree remove <wt_dir>` 与 `git branch -d <branch>`；
3. 确保最终 `git worktree list` 只剩主仓 1 个目录，`git branch` 只剩 `main` 分支，磁盘上零临时残留！

---

## 5. 免代码平替方案（双线文档/表格隔离法）

日常用 AI 同时改两份关联方案或同一份主表的两个章节时，同样遵循“锁契约 -> 拆副本 -> 合主稿 -> 删临时夹”四步法：
1. 先把目录大纲和统一术语表锁死在《主文档 v1.0》里不动；
2. 新建 `任务A-市场篇副本/` 和 `任务B-财务测算副本/` 两个独立文件夹，分别开两个 AI 会话各自打磨校验；
3. 定稿核对无误后粘贴合回《主文档》，**当场删除两个临时副本文件夹**，彻底杜绝“最终版_v3_真正最终版”互相覆盖。

---

## 6. 量化验收命令

```bash
# 验收当前 starter.py 改进进度（将在真实临时 Git 仓库中实测 worktree 隔离与清理）
python3 labs/S5-M08-worktree-parallel/verify.py

# 验证标准参考答案 solution.py（全部 4 项硬核指标 100% 通过，返回退出码 0）
python3 labs/S5-M08-worktree-parallel/verify.py --solution
```
