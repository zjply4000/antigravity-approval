# DESIGN — Pinned command rules (sha256 审计放行规则，暂缓实现)

状态：**设计记录，未实现**（2026-10-02 定稿思路；实现前先重读本文与当时代码是否漂移）。
动机见同批 Tier 1 改动（重定向路径防线 + git force_ask + 白名单扩容）。

## 1. 问题

Tier 2（Jev）判定 `python <script>.py <flags>` 时只能看到命令行文本，看不到脚本
内容——它对 `--self-test` 这类 flag 的放行本质是按名字猜语义（flag 无标准语义）。
人审一次脚本后没有任何机制"记住"这次审计：同样的命令下次要么再弹窗（烦）、
要么被 LLM 凭表面文本放行（不严）。

## 2. 规则形态（最小化，无通配）

```jsonc
// ~/.zcode/jev_approval/rules.json （antigravity 为 ~/.antigravity/...）
{
  "rules": [
    {
      "id": "pin_8f3a2c",
      "project": "D:\\Projects\\Huawei\\Photos",     // 规则只在该工作区生效
      "argv": ["python", "data-local/stage4d/stage4d_canary_a_real_observer.py",
               "--self-test"],                        // 精确 token 序列，非前缀
      "script_sha256": "3f9c1e…",                     // 入口脚本内容 pin
      "pinned_at": "2026-10-02"
    }
  ]
}
```

匹配条件（全部满足才放行，任一不满足 → 照常走 Tier 2/ask）：

1. 规则的 `project` 等于当前工作区根（normcase 后比较）；
2. 分段 tokenize 后 argv **精确等于** `argv` 字段（不多不少；变体需另 pin）；
3. argv 中的 `.py` 路径按命令 cwd 解析为绝对路径，本地现算 sha256 **等于** pin 值。

生效位置：Tier 1 内（hashlib 是 stdlib；`check_file_target` 本就触碰文件系统，
不破坏分层）。命中 → 确定性 allow，零 LLM 成本，审计日志标 `tier=pinned_rules`。

## 3. 存储位置是安全边界（不可妥协）

- **规则文件必须放 user 级、工作区外**。放工作区内 = agent 可写 = agent 给自己
  发权限（file_guard 对工作区内写是放行的），规则表变成提权通道。
- 配套防线（已在 2026-10-02 落地）：bash 重定向目标过 `check_file_target`，
  agent 无法用 `>>` 改 user 级文件；`jev-pin` 命令与规则文件路径列入
  force_ask 保护清单（agent 侧任何触碰必弹窗）。
- 分层复用现有 config 约定：规则放 user 级文件、按 `project` 分键即天然项目
  作用域；绝大多数规则属于单个项目，跨项目规则放全局段（罕见）。

## 4. 生命周期：人触发添加，系统自动失效

| 阶段 | 谁做 | 说明 |
|------|------|------|
| 创建 | 人 | 手动 CLI pin；或 v2 半自动候选（见 §6）。**不要**做"点允许即自动 pin"——把一次性懒批准静默升级为永久授权 |
| 失效 | 系统 | 内容一变 hash 不匹配 → 自动回落 ask，即强制重审点；文件删除/改名 → 规则惰性失效 |
| 清理 | 可选 | 死条目定期提示/清除，纯卫生 |

## 5. CLI 交互（jev-pin）

```text
PS D:\Projects\Huawei\Photos> jev-pin "python data-local/stage4d/xxx.py --self-test"

  命令     python data-local/stage4d/xxx.py --self-test
  解析     1 个片段 · 无重定向/替换/管道 ✓
  脚本     D:\...\xxx.py · 1276 行 · 修改于 2026-10-01 14:22
  sha256   3f9c1e…a720
  作用域   project = D:\Projects\Huawei\Photos
  ⚠ 这是持久授权：此内容从此免弹窗，内容一变自动失效。
    确认你已读过并审过这份脚本。 [y/N] y
  ✓ 已写入 pin_8f3a2c …
```

要点：
- 输入是**粘贴的整条命令**（与权限弹窗同一动线），CLI 与 evaluator 共用 tokenizer；
- 确认页即审计提醒页（路径/行数/mtime/hash），默认 N，**要求 TTY**（防 agent 管道喂 y；pin 永远人敲）；
- 同 argv 重复 pin 显示新旧 hash 对比（重审仪式），覆写需确认；
- 子命令：`--list` / `--remove <id>`；无通配、无"额外参数也放行"。

## 6. 与其他机制的关系

- **互补而非替代**："脚本内容喂给 Jev 评审"（暂缓的想法 B）覆盖没审过的新脚本
  （每次执行的 LLM 点审）；本机制覆盖审过的高频脚本（确定性免审）。两者都不做
  时，`python x.py` 类保持现状（Tier 2 按表面文本判，阈值兜底）。
- v2 候选收集：evaluator 落到 ask 且命令为 `python <工作区脚本>` 形态时，把
  (argv, hash, 时间戳) 追加到候选文件（仅记录非授权），人择优转正。自动发现、
  不自动信任。
- 与 photos 仓库 artifact pinning / BASELINE_PIN 纪律同构：批次收尾重 pin。

## 7. 实现清单（动手时）

1. `config.py`：Settings 增加只读 `rules` 字段（user 级文件解析，frozen dataclass 装 tuple）；
2. `deterministic.py`：`evaluate_tool_call` 白名单检查之前插 `pinned_rules` 段
   （项目匹配 → argv 精确匹配 → sha256 现算）；
3. `scripts/`：`jev_pin.py` CLI（复用 `split_chain`/`tokenize`/hash 计算）；
4. 保护清单：`jev-pin` 命令 + 规则文件路径 → force_ask；
5. 测试：匹配/不匹配/内容漂移/跨项目不生效/agent 写规则文件被拦。
