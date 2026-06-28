# Chinese Stock-Friend README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GitHub 说明改成股友能直接看懂、复制提问并安全使用焚诀的中文指南。

**Architecture:** 根 README 保持短小，承担分享、安装和首次使用入口；包内 README 承担完整的股友使用说明，并把 CLI、六策略和工程验证放到后半部分。代码、Skill 契约和数据库均不改动。

**Tech Stack:** GitHub Flavored Markdown、Python unittest、GitHub Actions

---

### Task 1: 改写分享首页

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 将首页改成股友入口**

首页按以下顺序编写：一句话定位、适用场景、安装文本、最小输入、三条复制提问模板、输出解释、能力边界、详细说明链接。删除首页中的工程闭环术语清单，把技术细节留给包内 README。

- [ ] **Step 2: 检查首页语言**

Run:

```powershell
rg -n "Brier|dry-run|fixture|schema|migration|改版范围|根目录文档|Skill 内文档" README.md
```

Expected: 无匹配；首页不向普通股友展示维护术语。

- [ ] **Step 3: 提交首页改写**

```powershell
git add README.md
git commit -m "docs: rewrite Chinese stock-friend landing page"
```

### Task 2: 改写完整使用说明

**Files:**
- Modify: `a-stock-signal-lab/README.md`

- [ ] **Step 1: 编写口语化使用说明**

前半部分包含：焚诀能帮什么、最好提供哪些信息、已买持仓/做 T/新买观察三类可复制提问、五种模式的中文解释、输出阅读方法、拒绝判断的情况。后半部分保留安装、CLI、六策略、验证治理和工程文档入口。

- [ ] **Step 2: 检查必要场景和风险边界**

Run:

```powershell
rg -n "已经买入|做 T|新买|买入价格|大致时间|失效条件|下一检查点|不自动下单|不构成投资建议" a-stock-signal-lab/README.md
```

Expected: 每个关键词至少出现一次。

- [ ] **Step 3: 提交完整说明**

```powershell
git add a-stock-signal-lab/README.md
git commit -m "docs: add conversational Chinese Fenjue guide"
```

### Task 3: 文档与回归验证

**Files:**
- Test: `README.md`
- Test: `a-stock-signal-lab/README.md`
- Test: `a-stock-signal-lab/tests/test_ci_contract.py`

- [ ] **Step 1: 检查 Markdown 结构和链接目标**

Run:

```powershell
git diff --check
Test-Path a-stock-signal-lab/SKILL.md
Test-Path a-stock-signal-lab/docs/engineering
Test-Path a-stock-signal-lab/docs/superpowers/specs
```

Expected: `git diff --check` 退出码为 0，三个路径均为 `True`。

- [ ] **Step 2: 运行完整测试和质量脚本**

Run from `a-stock-signal-lab/`:

```powershell
python -m ruff check fenjue scripts tests --select E9,F63,F7,F82
python -m unittest discover -s tests -v
python scripts/ci_migration_dry_run.py
python scripts/ci_fixture_replay.py
python scripts/ci_shadow_baseline_regression.py
```

Expected: lint 通过；80 项测试零失败；迁移、fixture 和 baseline regression 均退出 0。

### Task 4: 发布到 GitHub

**Files:**
- Commit: `README.md`
- Commit: `a-stock-signal-lab/README.md`
- Commit: design and plan documents

- [ ] **Step 1: 核对发布范围**

```powershell
git status -sb
git diff origin/main...HEAD --stat
```

Expected: 只包含两份 README、一份设计稿和一份执行计划。

- [ ] **Step 2: 推送分支并创建 PR**

```powershell
git push -u origin codex/chinese-stock-friend-readme
```

随后通过 GitHub 插件创建以 `main` 为基线的 PR，标题为 `[codex] rewrite Chinese stock-friend README`。

- [ ] **Step 3: CI 通过后合并**

确认 lint、unit tests、migration dry-run、fixture replay、shadow-vs-baseline regression 全部成功，再使用 merge commit 合入 `main`，保留文档设计与实施提交。
