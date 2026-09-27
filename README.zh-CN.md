[English](README.md) | [简体中文](README.zh-CN.md)

> 本文档是 [English README](README.md) 的简体中文版本。项目行为、配置项和安全边界以代码及最新英文文档为准。

# antigravity-approval

一个面向 Antigravity 的 fail-closed（失败或无法判断时回退到 `ask`）`PreToolUse` 权限防护栏（guardrail）：把确定性的本地规则与 TypeSafe Jev 分类结合起来，用于处理含糊的工具调用。无法确定或涉及策略敏感的操作一律回退为人工审批（`ask`）。

本仓库同时承载共享的 **`jev-evaluator` policy core**——即 `jev_eval` Python 包。[zcode-approval](https://github.com/zjply4000/zcode-approval) 复用这一核心，把同一套策略引擎适配到 ZCode 的 hook 协议上。

> **Antigravity 2.0 限制：**在当前构建版本上，对 `run_command` 作出 `allow` 判定并不会抑制宿主的权限弹窗——白名单命令仍会弹出提示，除非把它们加入宿主的全局授权列表。`deny` 判定则会被宿主执行。详细说明与注意事项见[已知的 Antigravity 宿主限制](#已知的-antigravity-宿主限制)。

## 评估流程

这是一个 Antigravity 的 `PreToolUse` hook，在工具调用执行之前对其进行审查。评估分层进行、确定性规则优先：本地快速的 Tier 1（白名单、blocklist、网络门禁、路径守卫）不产生任何网络流量即可裁定无歧义的命令；含糊的命令升级到 Tier 2——一次受硬性墙钟时限约束的 TypeSafe Jev 分类调用。Tier 2 的每一种失败——超时、API 错误、缺少 key、应答格式非法——都会 fail closed 回退到 `ask`，因此当评估器给不出答案时，命令会回退为人工确认，而不是被静默放行。

## 文件写入与会话产物

工作区之内，会修改文件的工具（`write_to_file`、`replace_file_content`、`multi_replace_file_content`）一律 `ask`——v1 从不自动放行任何文件修改。目标位于所有工作区之外时判为 `deny`（路径守卫）；**唯一例外**是宿主认可的按会话划分的 artifact 目录，也就是 payload 通过 `artifactDirectoryPath` 提供的目录（`~/.gemini/antigravity/brain/<conversationId>/…`）——Antigravity 在其中存放自己的任务产物与实施计划：对这一目录的写入会被自动放行（`allow`，tier `artifact`）。这条自动放行被刻意收得很窄——位于 `.system_generated/` 之下的目标以及任何 `*.metadata.json` 都会回退为 `ask`，因此 agent 无法借这条自动放行路径改写对话记录或 artifact 元数据。

## 已知的 Antigravity 宿主限制

在 Antigravity 2.0 应用上，hook 作出的 `allow` **不会**抑制 `run_command` 的权限弹窗；只有宿主自己的 `userSettings/globalPermissionGrants/allow` 列表才有这个效果。`deny` *会*被执行。因此在当前构建上，这个 hook 的实际价值是一条**只含 `deny` 的 guardrail** 加上 artifact 自动放行；白名单命令仍然会弹窗，除非你把它们加入那个全局列表。证据与复现步骤：`docs/FINDINGS-antigravity-hook-decisions.md`。

注意事项：“宿主忽略 `allow`”这一行为只在 `run_command` 上得到过验证。宿主是否同样忽略 file tools 的 `allow`（即 artifact 写入是否仍会弹窗）在当前构建上**尚未验证（unverified）**；artifact 的 `allow` 判定本身符合已文档化的契约，在任何会执行 `allow` 的宿主上都会生效。

## 残余风险

> blocklist 是纵深防御（defense-in-depth），不是安全边界（security boundary）。一条从未见过的破坏性命令，如果被 Jev 以置信度 ≥ 0.96 分类为 `standard_dev`，就会被自动放行。缓解手段：置信度阈值、blocklist、命令链拆分，以及对审计日志的复查。复查日志之后，可将 `CONFIDENCE_THRESHOLD` 向 0.98 方向调高。

## 安装

在仓库根目录下执行（Windows，Git Bash 或 PowerShell）：

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe scripts/install_hook.py
```

安装脚本会用本机 venv 的解释器把 `hooks.template.json` 渲染为 `.agents/hooks.json`，并打印一段供全局安装使用的配置块（见[全局安装](#全局安装)）。如果脚本报告 `typesafe-sdk` 不可导入，先把它装进 venv：

```bash
.venv/Scripts/python.exe -m pip install typesafe-sdk
```

接着配置 TypeSafe API key。把 `TYPESAFE_API_KEY=...` 写进 `~/.gemini/config/jev.env`（文件不存在则新建）。**切勿把 key 提交进版本库**——它保存在你的用户配置目录中，位于仓库之外。

用 live smoke 脚本验证配置（发起一次真实 Jev 调用；仅供手动执行）：

```bash
.venv/Scripts/python.exe scripts/smoke_live.py
```

运行成功会输出类似 `category=standard_dev confidence=0.9xx latency_ms=~100` 的一行。如果缺少 key，会得到 `TYPESAFE_API_KEY is not configured (env or ~/.gemini/config/jev.env).`，退出码为 1。最后，**重启 Antigravity**，让它加载新的 hook 配置。

## 配置

优先级：进程环境变量 → 工作区 `.agents/jev.env` → 用户级 `~/.gemini/config/jev.env` → 内置默认值。文件使用 `KEY=VALUE` 行（不做 shell 插值）；API key 应放在**用户级文件**中（绝不提交；`.agents/jev.env` 如果存放敏感信息，必须加入 gitignore）。

| 配置项 | 默认值 | 含义 |
|---|---|---|
| `TYPESAFE_API_KEY` | —（Tier 2 必需） | Bearer 令牌 |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | 端点覆盖（用于测试与 mock） |
| `CONFIDENCE_THRESHOLD` | `0.96` | 自动放行所需的最低 Choice 置信度 |
| `EVAL_TIMEOUT_MS` | `1500` | Jev 调用时间预算 → `RetryPolicy(timeout=EVAL_TIMEOUT_MS/1000, max_retries=1, backoff_max=0.2)` |
| `ALLOW_NETWORK_COMMANDS` | `false` | `false` → 网络命令在 Tier 1、尚未送到 Jev 之前就被 `force_ask`。`true` → 网络命令跳过该门禁；当 Jev 以置信度 ≥ 阈值将其分类为 `network_outbound` 时，可被自动放行 |
| `JEV_FAIL_MODE` | `closed` | `closed` → 出错时升级为 `ask`；`open` → 出错时直接输出 `allow`（仅限沙箱/CI 使用；本 README 对此有醒目警告） |
| `JEV_LOG_FILE` | `~/.gemini/logs/jev_evaluator.log` | 审计日志路径 |

**Windows 说明：**hook 进程由 Antigravity GUI 启动，**不会**继承 shell 配置文件中的环境变量（凡写在 `.bashrc`、PowerShell profile 等文件里的变量都继承不到）。因此配置不只从进程环境变量读取，也会从文件加载——请把 key 和所有覆盖项放进 `~/.gemini/config/jev.env`。

## 全局安装

`.agents/hooks.json` 只覆盖当前这一个工作区。要让每个 Antigravity 会话都评估命令，请把安装脚本打印在 `--- global install: paste the block below into ~/.gemini/config/hooks.json ---` 之后的那段配置块，粘贴进 `~/.gemini/config/hooks.json`。其形式如下（解释器与评估器路径因机器而异——请使用你自己安装脚本的输出，不要照抄本示例）：

```json
{
  "jev-evaluator": {
    "enabled": true,
    "PreToolUse": [
      {
        "matcher": "run_command|write_to_file|replace_file_content|multi_replace_file_content",
        "hooks": [
          {
            "type": "command",
            "command": "\"<path/to/antigravity-approval>/.venv/Scripts/python.exe\" \"<path/to/antigravity-approval>/scripts/jev_evaluator.py\" --event PreToolUse",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

编辑 `hooks.json` 之后请重启 Antigravity。

## 调优

每一次判定都会追加到审计日志 `~/.gemini/logs/jev_evaluator.log`（JSONL，每行一个对象，达到 5 MB 轮转，保留 3 份备份）。复查日志可以看出是哪一层在什么情况下作出了什么判定：

```bash
grep -o '"tier": "[^"]*"' ~/.gemini/logs/jev_evaluator.log | sort | uniq -c
grep -o '"decision": "[^"]*"' ~/.gemini/logs/jev_evaluator.log | sort | uniq -c
```

在 `~/.gemini/config/jev.env`（或经由进程环境变量）作出的调整，会在下一次 hook 调用时生效：

- **`CONFIDENCE_THRESHOLD`** —— 调高（例如 `0.98`）意味着只自动放行近乎确定的判定；调低则更少的边界情况命令会被送去 `ask`。从默认值 `0.96` 起步，复查日志后再收紧。
- **`ALLOW_NETWORK_COMMANDS`** —— 保持 `false`，则每条网络命令（包括包安装）都会在咨询 Jev 之前先经过 `ask`。只有当你接受 Jev 对置信度达到阈值的 `network_outbound` 命令自动放行时，才设为 `true`。

**`JEV_FAIL_MODE=open` 警告：**默认的 `closed` 会把 Tier 2 错误升级为 `ask`。若改为 `JEV_FAIL_MODE=open`，则 Jev 调用一旦出错或超时就直接输出 `allow`——一次服务故障就会变成静默放行。只在没有可被破坏的重要数据的沙箱或 CI 中使用；绝不要用于有真实工作或凭据的机器。

## 卸载

从 `~/.gemini/config/hooks.json`（全局）中删除 `jev-evaluator` 配置块，和/或删除 `.agents/hooks.json`（按工作区），然后重启 Antigravity。可选：连 venv（`.venv/`）与 `~/.gemini/config/jev.env` 一起删除，把 key 从磁盘上清除。
