## 限额说明

为了更好的了解 API-Inference 的使用情况，您可以通过 HTTP 响应头查看限额相关信息，包括用户限额、用户剩余额度，模型限额、模型剩余额度。用户额度是指当前用户所有模型总额度，模型维度额度指当前请求模型的额度。

### 响应头说明

| 响应头 | 描述 | 示例值 |
|--------|------|--------|
| `modelscope-ratelimit-requests-limit` | 用户当天限额 | 2000 |
| `modelscope-ratelimit-requests-remaining` | 用户当天剩余额度 | 500 |
| `modelscope-ratelimit-model-requests-limit` | 模型当天限额 | 500 |
| `modelscope-ratelimit-model-requests-remaining` | 模型当天剩余额度 | 20 |

> 💡 **提示**：本代理服务会**被动捕获**这些响应头信息，无需额外请求。

---

## 示例 Demo

```python
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_MODELSCOPE_API_KEY",  # 请替换成您的 ModelScope Access Token
    base_url="https://api-inference.modelscope.cn/v1/"
)

response = client.chat.completions.create(
    model="Qwen/Qwen3.5-35B-A3B",  # ModelScope Model-Id
    messages=[
        {
            'role': 'system',
            'content': 'You are a helpful assistant.'
        },
        {
            'role': 'user',
            'content': '用 python 写一下快排'
        }
    ],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content, end='', flush=True)
```

---

## 可用模型

| 模型 ID | 描述 |
|---------|------|
| `Qwen/Qwen3-Coder-480B-A35B-Instruct` | Qwen 超大编码模型 |
| `Qwen/Qwen3-235B-A22B-Thinking-2507` | Qwen 思考模型 |
| `Qwen/Qwen3.5-122B-A10B` | Qwen 旗舰模型 |
| `Qwen/Qwen3.5-35B-A3B` | Qwen 主力模型 |
| `ZhipuAI/GLM-5` | 智谱 GLM-5 |
| `moonshotai/Kimi-K2.5` | 月之暗面 Kimi |
| `MiniMax/MiniMax-M2.5` | MiniMax M2.5 |