# Free API Forwarder

> **零额外消耗的智能模型调度**
> 自动轮询模型池、429 时自动降档重试，对外暴露统一 OpenAI 兼容接口

## 快速开始

### 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/myrzx/free-api-forwarder/master/setup.sh | bash
```

脚本会自动：检测 Python → 提示输入 API Key → 克隆仓库 → 安装依赖 → 配置环境

---

### 手动安装

#### 1. 获取 ModelScope API Key

1. 访问 [ModelScope](https://modelscope.cn/) 并登录/注册
2. 点击右上角头像 → **个人中心** → **访问令牌**
3. 点击 **创建令牌** 或复制已有令牌
4. 保存你的 API Key（格式类似 `ms-xxxxx`）

#### 2. 配置

编辑 `config/tier-config.json`，填入你的 API Key：

```json
{
  "api_key": "YOUR_API_KEY_HERE",  // 👈 填入你的 ModelScope API Key
  "base_url": "https://api-inference.modelscope.cn/v1",
  "tiers": { ... }
}
```

> **提示**：也可以通过环境变量配置：`export MODELSCOPE_API_KEY=ms-xxxxx`

#### 3. 安装依赖

```bash
pip install -r requirements.txt
```

#### 4. 启动服务

```bash
python src/modelscope_proxy.py
```

默认监听 `http://localhost:8080`

#### 5. 接入应用

将你的应用 API 地址指向代理服务即可：

```python
from openai import OpenAI

client = OpenAI(
    api_key="any",  # 代理不校验 key，随便填
    base_url="http://localhost:8080/v1"
)

response = client.chat.completions.create(
    model="flagship",  # 可选：flagship / normal / fast
    messages=[{"role": "user", "content": "你好"}]
)
```

---

## 三档模型路由

| 档位 | 说明 | 包含模型 |
|------|------|----------|
| `flagship` | 旗舰级 - 超大模型，最强能力 | Qwen/Qwen3.5-122B-A10B, Qwen/Qwen3-Coder-480B-A35B-Instruct |
| `normal` | 普通级 - 均衡型主力模型 | Qwen/Qwen3.5-35B-A3B, ZhipuAI/GLM-5 |
| `fast` | 快速级 - 兜底备用 | Qwen/Qwen3-235B-A22B-Thinking-2507, moonshotai/Kimi-K2.5, MiniMax/MiniMax-M2.5 |

### 使用方式

```json
{
  "model": "flagship",  // 或 "normal" / "fast"
  "messages": [...]
}
```

### 自动降级逻辑

```
请求 flagship → 429? → 换同档其他模型重试
              → 仍 429? → 降档到 normal 重试
              → 仍 429? → 降档到 fast 重试
              → 仍 429? → 返回 503 错误
```

---

## 配额监控（零消耗）

```bash
# 查看当前配额
curl http://localhost:8080/quota

# 查看历史记录
curl http://localhost:8080/quota/history

# 查看档位配置
curl http://localhost:8080/tiers
```

---

## 自定义模型分组

编辑 `config/tier-config.json`：

```json
{
  "api_key": "YOUR_API_KEY",
  "base_url": "https://api-inference.modelscope.cn/v1",
  "tiers": {
    "flagship": {
      "models": ["你的模型1", "你的模型2"]
    },
    ...
  }
}
```

重启代理即可生效。

---

## 项目结构

```
free-api-forwarder/
├── src/
│   ├── modelscope_proxy.py      # 代理服务核心
│   └── check_all_models.py      # 批量查询模型配额
├── config/
│   └── tier-config.json         # 配置文件（填入你的 API Key）
├── docs/
│   └── ModelScopeTestApi.md     # ModelScope API 文档
├── requirements.txt
└── README.md
```

---

## 关键设计

- **被动监控**：仅捕获已发生的请求，绝不主动查询
- **自动降级**：429 时自动同档轮换 → 跨档降级
- **内存存储**：重启后自动重置（符合配额重置周期）
- **配置驱动**：通过 JSON 轻松扩展模型分组

---

## License

MIT