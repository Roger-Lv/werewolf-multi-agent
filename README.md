# 狼人杀多Agent自主博弈系统

让不同厂商的大语言模型作为独立玩家参与狼人杀游戏，进行完全自主的博弈。人类也可以作为玩家参与其中。

## 核心特性

- **多模型博弈**：不同 LLM（GLM、Kimi、DeepSeek、GPT、MiniMax 等）作为独立玩家，各自决策
- **人类参与**：人类玩家可通过 Web 前端实时参与游戏，与 LLM 对抗
- **信息隔离**：每个 Agent 只知道自己的身份和公开信息，绝不能看到其他玩家的角色——这是系统最重要的底线
- **双端分离架构**：GM（裁判）和 Player Agent 分别使用独立 LLM 调用，GM 掌握全局、玩家只看局部
- **并发优化**：夜晚行动和投票阶段使用 `asyncio.gather` 并发请求多个 LLM，提升游戏效率
- **上下文压缩**：当发言历史过长时，自动调用摘要模型压缩上下文，避免 token 爆炸
- **实时 Web 前端**：Vue 3 SPA + WebSocket，实时展示游戏进程
- **氛围感 UI**：毛玻璃面板、角色专属光效、阶段动态色调、叙事化事件日志

## 项目结构

```
werewolf/
  config.yaml                # 游戏配置（角色分配、模型选择、规则）
  config.yaml.template       # 配置模板（不含 API Key，用于新用户参考）
  pyproject.toml             # uv 项目配置 + Python 依赖
  .gitignore                 # Git 忽略规则（排除 config.yaml 等敏感文件）
  src/werewolf/
    __init__.py
    models.py                # Pydantic v2 数据模型 + ActionProvider 抽象
    llm_client.py            # 统一异步 LLM 客户端（OpenAI SDK 兼容）
    prompts.py               # GM/Player Prompt 构建逻辑
    config.py                # YAML 配置加载
    game_engine.py           # 核心异步状态机引擎
    human_player.py          # 人类玩家 WebSocket 交互层
    server.py                # FastAPI + WebSocket 服务端
    test_api.py              # API 连通性测试脚本
  frontend/
    package.json             # 前端依赖（Vue 3 + Pinia + TailwindCSS）
    vite.config.ts           # Vite 配置（含 API/WebSocket 代理）
    tailwind.config.js       # TailwindCSS 配置（角色色板+自定义动画）
    src/
      style.css              # 全局样式（毛玻璃、角色光效、阶段动画）
      main.ts                # 入口文件
      App.vue                # 主页面（阶段动态色调、角色信息横幅）
      types.ts               # TypeScript 类型定义
      components/
        GameBoard.vue        # 玩家面板（3×3网格、角色徽章、死亡效果）
        ChatLog.vue          # 事件日志（叙事化、阶段分隔、入场动画）
        HumanInput.vue       # 人类行动输入（角色专属光效、毛玻璃面板）
        ConnectPanel.vue     # 连接面板
      stores/
        gameStore.ts         # Pinia 状态管理 + WebSocket 通信
```

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                   Vue 3 SPA 前端                             │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │GameBoard │  │ ChatLog  │  │HumanInput│  │ConnectPnl│   │
│  │(玩家面板)│  │(事件日志)│  │(行动输入)│  │(连接面板)│   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│         │            │            │                          │
│         └─── Pinia gameStore ────┘                          │
│                    │ WebSocket + HTTP                       │
└────────────────────┼────────────────────────────────────────┘
                     │
┌────────────────────┼────────────────────────────────────────┐
│          FastAPI + WebSocket 服务端                          │
│                    │                                        │
│  ┌─────────┐  ┌───┴───┐  ┌──────────┐                      │
│  │HTTP API │  │ WS Mgr│  │Event CB  │                      │
│  │/api/state│ │连接池 │  │事件推送 │                      │
│  │/api/my-role││私密通道│ │信息隔离│                      │
│  └─────────┘  └───────┘  └──────────┘                      │
│                    │                                        │
│         ┌─────────┴──────────┐                              │
│         │   Game Engine      │                              │
│         │  (异步状态机)       │                              │
│         │                    │                              │
│         │  _run_night()      │                              │
│         │  _run_day_speech() │                              │
│         │  _run_day_vote()   │                              │
│         │  _hunter_shoot()   │                              │
│         └────────────────────┘                              │
│              │            │                                 │
│   ┌─────────┴──┐  ┌──────┴──────┐  ┌──────────────┐       │
│   │ GM (LLM)   │  │ LLM Players │  │Human Players │       │
│   │ 裁决全局   │  │ 独立决策     │  │WebSocket交互 │       │
│   └────────────┘  └─────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 信息隔离关键路径

1. **Prompt 层**：GM 掌握全局状态，只输出公开公告；Player Agent 的 Prompt 中只包含自己的角色、个人记忆、GM 广播、自己的私密信息
2. **WebSocket 层**：广播事件不含角色信息，私密行动请求（如查验结果、女巫药品状态）只发给对应玩家
3. **API 层**：`/api/my-role` 要求先建立 WebSocket 连接才能查询
4. **前端层**：游戏进行中角色信息仅供旁观/开发参考，人类玩家只能看到自己的角色

### 游戏引擎流程

```
游戏循环:
  ┌──→ _run_night() ──────────────────────────┐
  │     │                                     │
  │     │  并发: 狼人选目标 + 预言家查验        │
  │     │  串行: 女巫行动（需要狼人目标信息）   │
  │     │  GM 裁决夜晚结果                     │
  │     │  猎人死亡触发 → _hunter_shoot()      │
  │     │                                     │
  │     _run_day_speech() ──────────────────── │
  │     │                                     │
  │     │  串行: 每个存活玩家依次发言           │
  │     │  （后发言者可以听到前发言者的话）     │
  │     │                                     │
  │     _run_day_vote() ────────────────────── │
  │     │                                     │
  │     │  并发: 所有存活玩家同时投票           │
  │     │  GM 裁决投票结果                     │
  │     │  被淘汰者 → 猎人触发 → _hunter_shoot│
  │     │                                     │
  │     check_game_over() ───→ 胜方判定 ───┘  │
  │                                           │
  └─── 否 ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
      是 → game_over
```

**并发策略**：
- 狼人 + 预言家：`asyncio.gather` 并发（互不依赖）
- 女巫：串行在狼人之后（需要知道被杀者才能决定是否救人）
- 白天发言：串行（后发言者可以引用前发言者的话）
- 投票：`asyncio.gather` 并发（避免后投票者知道前投票者的选择）

**兜底机制**：
- LLM API 失败时，GM 使用确定性规则裁决（多数投票、随机选择等）
- 玩家行动失败时，使用随机合法行动替代
- JSON 解析失败时，自动从文本中提取 JSON

## 快速启动

### 前置要求

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）

### 1. 安装后端依赖

```bash
cd werewolf
uv sync
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 配置 API Key

```bash
cp config.yaml.template config.yaml
```

编辑 `config.yaml`，将所有 `<YOUR_API_KEY>` 和 `<YOUR_API_BASE_URL>` 替换为真实的 API 配置：

```yaml
game:
  gm:
    base_url: "https://cloud.infini-ai.com/maas/v1"
    api_key: "sk-xxxxxxxxxxxxx"
    model: "glm-5.1"
```

本项目推荐使用[无问芯穹（InfiniAI）](https://cloud.infini-ai.com)的统一 API 接口，兼容 OpenAI SDK 格式。可用模型包括：glm-5.1、kimi-k2.6、deepseek-v4-pro、gpt-5.4、minimax-m2.7 等。

> **注意**：`config.yaml` 包含 API Key 等敏感信息，已被 `.gitignore` 排除，不会被提交到 Git。配置模板 `config.yaml.template` 不含敏感信息，可供新用户参考。

### 4. 启动后端服务

```bash
uv run python -m werewolf.server
```

后端运行在 `http://localhost:8000`。

### 5. 启动前端（开发模式）

```bash
cd frontend
npm run dev
```

前端运行在 `http://localhost:5173`，自动代理 API 和 WebSocket 到后端。

### 6. 开始游戏

1. 打开浏览器访问 `http://localhost:5173`
2. 选择身份：旁观者（0号）或人类玩家（1-9号）
3. 点击"连接"
4. 点击"开始游戏"

如果你是人类玩家，游戏进行中你会在底部收到行动请求（选择杀人目标、发言、投票等），只有你能看到自己的角色和私密信息。

## 游戏规则

### 默认配置（9人局）

3 狼人 + 3 神职 + 3 村民：

| 角色 | 数量 | 能力 | 夜晚行动 |
|------|------|------|----------|
| 狼人 | 3 | 每晚选择杀人目标，白天伪装身份 | 选择击杀目标 |
| 预言家 | 1 | 每晚查验一人是否为狼人 | 查验目标身份 |
| 女巫 | 1 | 解药救人、毒药杀人，各只能用一次 | 决定是否救人/毒人 |
| 猎人 | 1 | 死亡时可以开枪带走一人 | 无（死亡触发） |
| 村民 | 3 | 无特殊能力，依靠推理和发言 | 无（睡觉） |

### 胜负条件

- **好人胜**：所有狼人被消灭
- **狼人胜**（满足其一即可）：
  - 狼人数量 ≥ 好人数量（人数优势）
  - 所有神职死亡（屠神边）
  - 所有平民死亡（屠民边）

游戏结束时会显示具体胜因（"所有狼人被消灭"、"屠神边——所有神职死亡"、"屠民边——所有平民死亡"、"狼人人数 ≥ 好人人数"）。

### 夜晚流程

```
夜幕降临
  ├─ 狼人选择击杀目标（多个狼人并发选择，取多数一致或随机裁决）
  ├─ 预言家查验目标身份（并发进行，与狼人同时）
  ├─ 女巫决定是否使用解药/毒药（串行进行，需要知道被杀者）
  ├─ GM 裁决夜晚结果（计算死亡、判断女巫药品效果）
  └─ 猎人触发检查（若猎人死亡且 can_shoot=True → 开枪）
```

### 白天流程

```
天亮了
  ├─ GM 公布昨夜死亡信息（不暴露死因和凶手角色）
  ├─ 白天发言：存活玩家依次发言（串行，后发言者可引用前发言者）
  ├─ 投票阶段：所有存活玩家并发投票选出淘汰者
  ├─ GM 裁决投票结果
  ├─ 猎人触发检查（若被投票淘汰且是猎人 → 开枪）
  └─ 检查胜负条件
```

### 可配置规则

在 `config.yaml` 的 `game.rules` 部分：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `witch_can_save_self_first_night` | `true` | 女巫首夜是否可使用解药自救 |
| `tie_vote_rule` | `"random"` | 平票处理方式（random = 随机淘汰一人） |
| `werewolf_disagree_rule` | `"random"` | 狼人意见不统一时的裁决方式 |
| `hunter_can_shoot_on_witch_poison` | `true` | 猎人被女巫毒死时是否仍可开枪 |
| `summary_threshold` | `15` | 触发上下文压缩的发言条数阈值 |

## 配置说明

### 角色分配

在 `config.yaml` 的 `game.roles` 中按顺序分配角色，数量必须与 `players` 配置的数量一致：

```yaml
game:
  roles:
    - werewolf   # 1号
    - werewolf   # 2号
    - werewolf   # 3号
    - seer       # 4号 预言家
    - witch      # 5号 女巫
    - hunter     # 6号 猎人
    - villager   # 7号
    - villager   # 8号
    - villager   # 9号
```

### 玩家类型

每个玩家可以是 LLM 或人类：

```yaml
players:
  1:
    type: "human"              # 人类玩家——无需 API 配置
    personality: "aggressive"
  2:
    type: "llm"                # LLM 玩家
    base_url: "https://cloud.infini-ai.com/maas/v1"
    api_key: "你的API_KEY"
    model: "kimi-k2.6"
    personality: "cunning"
```

人类玩家通过前端 Web 界面参与游戏，系统会通过 WebSocket 发送行动请求并等待人类响应。

### 性格特征

每个玩家分配一个性格，让不同模型展现不同风格：

| 性格 | 英文 | 特点 |
|------|------|------|
| 激进 | aggressive | 积极指控，倾向主动出击 |
| 狡诈 | cunning | 伪装能力强，善于误导 |
| 保守 | conservative | 谨慎发言，少冒险 |
| 理性 | analytical | 逻辑推理为主，引用证据 |
| 谨慎 | cautious | 避免站队，观望为主 |
| 大胆 | bold | 敢于冒险，大胆猜测 |
| 雄辩 | eloquent | 发言长且有力，善于说服 |
| 善于观察 | observant | 注意细节，捕捉矛盾 |
| 策略型 | strategic | 长远规划，有目的性 |

### GM 和摘要模型

GM 负责裁决游戏逻辑（夜晚结果、投票结果、胜负判定），摘要模型负责压缩过长的发言历史：

```yaml
game:
  gm:
    model: "glm-5.1"            # GM 用较强模型确保裁决准确
  summarizer:
    model: "glm-5.1"            # 摘要可用稳定模型避免速率限制
```

### 上下文压缩

当发言历史超过 `summary_threshold` 条时，引擎自动调用摘要模型压缩上下文：

```python
# 原始历史: 30条发言记录
# 压缩后: "第1-2轮: 狼人杀了4号，女巫救了4号..."（约200字摘要）
# 最新5条发言保留原文，其余替换为摘要
```

## API 接口

### HTTP

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/state` | GET | 获取当前游戏公开状态（玩家列表、阶段、轮次） |
| `/api/my-role/{player_id}` | GET | 获取人类玩家的私密角色信息（需先建立 WebSocket） |
| `/api/game/start` | POST | 启动游戏 |
| `/api/game/stop` | POST | 停止游戏 |

### WebSocket

| 端点 | 说明 |
|------|------|
| `/ws/game/0` | 旁观者连接——只接收广播事件 |
| `/ws/game/{1-9}` | 人类玩家连接——接收广播 + 私密行动请求 |

**消息类型**：

| 类型 | 方向 | 说明 |
|------|------|------|
| `progress` | 服务端→客户端 | 游戏进度通知（含 round/phase 用于同步状态） |
| `night_result` | 服务端→客户端 | 夜晚结果公告 |
| `seer_check_private` | 服务端→预言家 | 查验结果（私密） |
| `player_speech` | 服务端→客户端 | 玩家发言 |
| `player_vote` | 服务端→客户端 | 玩家投票 |
| `vote_result` | 服务端→客户端 | 投票结果公告 |
| `hunter_shoot` | 服务端→客户端 | 猎人开枪公告 |
| `game_over` | 服务端→客户端 | 游戏结束（揭示所有角色） |
| `action_request` | 服务端→人类玩家 | 请求人类提交行动 |
| `action_response` | 人类玩家→服务端 | 人类提交行动响应 |

## 使用其他 LLM API

系统通过 OpenAI SDK 兼容接口调用所有模型，只需修改 `base_url` 和 `api_key` 即可切换不同厂商：

| 厂商 | base_url | 说明 |
|------|----------|------|
| 无问芯穹 | `https://cloud.infini-ai.com/maas/v1` | 统一接入多家模型 |
| OpenAI | `https://api.openai.com/v1` | GPT 系列 |
| DeepSeek | `https://api.deepseek.com/v1` | DeepSeek 系列 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | GLM 系列 |
| Anthropic | 需额外适配 | Claude 系列暂不支持 response_format |

系统支持混合使用不同厂商的 API——不同的玩家可以使用不同的 `base_url` 和 `api_key`。

## 前端设计

### 视觉特色

- **阶段动态色调**：夜晚=紫蓝渐变，白天发言=暖金，投票=红色警示，结束=绿色胜利
- **毛玻璃面板**：`glass-panel` / `glass-panel-dark` 提供空间层次感
- **角色专属光效**：狼人红光、预言家蓝光、女巫紫光、猎人金光、村民绿光
- **3×3 网格面板**：玩家卡片有角色渐变徽章、死亡覆盖效果、自己的卡片有金色光环脉动
- **叙事化事件日志**：入场浮升动画、左边框颜色区分事件类型、阶段分隔标记

### 自定义 CSS 类

| 类名 | 说明 |
|------|------|
| `glass-panel` | 毛玻璃浅色面板 |
| `glass-panel-dark` | 毛玻璃深色面板 |
| `role-badge-{role}` | 角色渐变徽章（圆形） |
| `role-border-{role}` | 角色专属光效边框 |
| `btn-{role}` | 角色专属渐变按钮 |
| `progress-bar` | 进度指示器（细条样式） |
| `phase-divider` | 阶段分隔标记 |
| `death-overlay` | 死亡覆盖效果 |

## 生产部署

前端构建后可直接由 FastAPI 提供静态文件服务：

```bash
cd frontend
npm run build
# dist/ 目录会被后端自动挂载到 /static
```

然后只需运行后端即可同时提供前端页面：

```bash
uv run python -m werewolf.server
# 访问 http://localhost:8000/static/ 即可
```

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+ / FastAPI / uvicorn / asyncio |
| LLM 调用 | OpenAI SDK (兼容格式) / httpx / tenacity (重试) |
| 数据模型 | Pydantic v2 |
| 前端 | Vue 3 / Vite / Pinia / TypeScript / TailwindCSS |
| 通信 | WebSocket (实时推送) + HTTP REST (状态查询) |
| 包管理 | uv (后端) / npm (前端) |

## 验证 API 连通性

运行内置测试脚本验证模型是否可用：

```bash
uv run python -m werewolf.test_api
```

该脚本会尝试调用配置中的每个模型，输出连通状态和响应示例。

## 信息隔离安全说明

这是本系统最重要的设计约束。LLM 存在"知道全局提示词就假装不知道"的缺陷，因此：

1. **严禁单 Prompt 方案**：绝不把所有玩家身份写在一个 System Prompt 里
2. **代码级隔离**：Player Agent 的 messages 列表中，只包含它自己的身份、记忆、GM 广播、私密信息
3. **WebSocket 隔离**：广播事件不含角色信息，私密行动请求只发给对应玩家
4. **API 隔离**：`/api/my-role` 要求先建立 WebSocket 连接
5. **Prompt 双括号**：所有包含 JSON 示例的 Prompt 模板使用 `{{ }}` 双括号转义，避免 Python `.format()` 误解析

## License

MIT