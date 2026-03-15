#!/usr/bin/env python3
"""批量查询所有模型的配额信息（从 tier-config.json 读取模型列表）"""

import json
import os
import requests

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/tier-config.json")


def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 加载配置失败：{e}")
        return None


def get_api_key():
    """获取 API Key，优先从环境变量"""
    return os.getenv("MODELSCOPE_API_KEY") or (load_config() or {}).get("api_key", "")


def get_base_url():
    """获取 Base URL"""
    return (load_config() or {}).get("base_url", "https://api-inference.modelscope.cn/v1")


def load_models_from_config():
    """从 tier-config.json 加载所有模型"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)

        models = []
        tiers = config.get("tiers", {})

        for tier_name, tier_info in tiers.items():
            tier_models = tier_info.get("models", [])
            for model in tier_models:
                if model not in models:  # 避免重复
                    models.append((model, tier_name))

        return models
    except Exception as e:
        print(f"❌ 加载配置失败：{e}")
        return []


def check_model_quota(model_id, api_key, base_url):
    """发送一个最小请求来获取配额头信息"""
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1
            },
            timeout=30
        )

        headers = response.headers
        return {
            "model": model_id,
            "status": response.status_code,
            "user_limit": headers.get("modelscope-ratelimit-requests-limit"),
            "user_remaining": headers.get("modelscope-ratelimit-requests-remaining"),
            "model_limit": headers.get("modelscope-ratelimit-model-requests-limit"),
            "model_remaining": headers.get("modelscope-ratelimit-model-requests-remaining")
        }
    except Exception as e:
        return {"model": model_id, "error": str(e)}


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("ModelScope 模型配额批量查询")
    print("=" * 80 + "\n")

    # 获取配置
    api_key = get_api_key()
    base_url = get_base_url()

    if not api_key:
        print("❌ 未配置 API Key，请在 config/tier-config.json 中设置 api_key 或设置环境变量 MODELSCOPE_API_KEY")
        exit(1)

    # 从配置加载模型
    model_tier_list = load_models_from_config()

    if not model_tier_list:
        print("❌ 没有找到模型配置，请检查 tier-config.json")
        exit(1)

    print(f"📋 共 {len(model_tier_list)} 个模型待查询\n")

    results = []
    for i, (model, tier) in enumerate(model_tier_list, 1):
        print(f"[{i}/{len(model_tier_list)}] 查询：{model} ({tier})")
        result = check_model_quota(model, api_key, base_url)
        result["tier"] = tier
        results.append(result)

        if "error" in result:
            print(f"  ❌ 错误：{result['error']}")
        else:
            user_rem = result.get("user_remaining", "N/A")
            model_rem = result.get("model_remaining", "N/A")
            model_lim = result.get("model_limit", "N/A")
            print(f"  ✅ 用户剩余：{user_rem} | 模型剩余：{model_rem}/{model_lim}")

    print("\n" + "=" * 80)
    print("汇总（按 tier 分组）")
    print("=" * 80)

    # 按 tier 分组显示
    tier_groups = {}
    for r in results:
        if "error" not in r:
            tier = r.get("tier", "unknown")
            if tier not in tier_groups:
                tier_groups[tier] = []
            tier_groups[tier].append(r)

    for tier_name in ["flagship", "normal", "fast"]:
        if tier_name in tier_groups:
            print(f"\n【{tier_name.upper()}】")
            print(f"  {'模型':<50} {'用户剩余':<10} {'模型剩余':<12}")
            print("  " + "-" * 72)
            for r in tier_groups[tier_name]:
                model_name = r["model"][:48] + ".." if len(r["model"]) > 50 else r["model"]
                user_rem = str(r.get("user_remaining", "N/A"))
                model_info = f"{r.get('model_remaining', 'N/A')}/{r.get('model_limit', 'N/A')}"
                print(f"  {model_name:<50} {user_rem:<10} {model_info:<12}")