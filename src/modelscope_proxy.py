#!/usr/bin/env python3
"""
ModelScope API 代理服务 - 智能路由版
- 三挡模型池 (flagship/normal/fast) 自动轮询
- 429 时自动切换同挡内下一模型并重试
- 同挡耗尽后自动降档
- 实时显示配额变化
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from flask import Flask, request, Response, jsonify
import requests
from typing import Dict, Optional, List, Tuple

# 配置
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/tier-config.json")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8080"))


def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载配置失败：{e}")
        return None


def get_api_key():
    """获取 API Key，优先从环境变量"""
    return os.getenv("MODELSCOPE_API_KEY") or (load_config() or {}).get("api_key", "")


def get_base_url():
    """获取 Base URL"""
    return (load_config() or {}).get("base_url", "https://api-inference.modelscope.cn/v1")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Flask 应用
app = Flask(__name__)

# 配额信息存储（线程安全）
quota_store = {
    "user_limit": None,
    "user_remaining": None,
    "model_limit": None,
    "model_remaining": None,
    "last_model": None,
    "last_update": None,
    "history": []
}
quota_lock = threading.Lock()

# 模型轮询状态（线程安全）
model_state = {
    "round_robin_index": {},  # tier -> current index
    "model_usage_count": {}   # model -> usage count in current period
}
state_lock = threading.Lock()


def load_tier_config():
    """加载层级配置"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载 tier 配置失败：{e}")
        return None


def get_models_for_tier(tier_name: str) -> List[str]:
    """获取某一层级的所有模型"""
    config = load_tier_config()
    if not config:
        return []
    return config.get("tiers", {}).get(tier_name, {}).get("models", [])


def get_next_model_in_tier(tier_name: str, exclude_model: Optional[str] = None) -> Optional[str]:
    """
    获取某层级的下一个模型（轮询）
    exclude_model: 要排除的模型（上次请求失败的）
    """
    models = get_models_for_tier(tier_name)
    if not models:
        return None

    with state_lock:
        if tier_name not in model_state["round_robin_index"]:
            model_state["round_robin_index"][tier_name] = 0

        start_idx = model_state["round_robin_index"][tier_name]
        attempts = 0

        while attempts < len(models):
            idx = (start_idx + attempts) % len(models)
            candidate = models[idx]

            if candidate != exclude_model:
                # 更新索引到下一个位置
                model_state["round_robin_index"][tier_name] = (idx + 1) % len(models)
                return candidate

            attempts += 1

        return None


def get_fallback_order() -> List[str]:
    """获取降档顺序"""
    config = load_tier_config()
    if not config:
        return ["flagship", "normal", "fast"]
    return config.get("fallback_order", ["flagship", "normal", "fast"])


def select_model_for_request(requested_model: str) -> Tuple[str, str]:
    """
    根据请求的 model 字段选择实际要使用的模型
    返回：(实际模型，使用的 tier)

    如果 requested_model 是 tier 名称 (flagship/normal/fast)，则从该 tier 选模型
    如果不是已知 tier，则直接使用该 model
    """
    valid_tiers = {"flagship", "normal", "fast"}

    if requested_model in valid_tiers:
        selected = get_next_model_in_tier(requested_model)
        if selected:
            return selected, requested_model
        else:
            logger.warning(f"Tier '{requested_model}' 没有可用模型")
            return requested_model, requested_model

    # 如果不是 tier 名称，可能是用户直接指定了具体模型
    # 或者是一个别名，这里直接返回原 model
    return requested_model, "direct"


def extract_quota_from_headers(headers: Dict) -> Dict:
    """从响应头提取配额信息"""
    quota_info = {}

    header_mapping = {
        "modelscope-ratelimit-requests-limit": "user_limit",
        "modelscope-ratelimit-requests-remaining": "user_remaining",
        "modelscope-ratelimit-model-requests-limit": "model_limit",
        "modelscope-ratelimit-model-requests-remaining": "model_remaining"
    }

    for header_name, key in header_mapping.items():
        if header_name.lower() in {k.lower() for k in headers}:
            # 大小写不敏感查找
            actual_key = next(k for k in headers if k.lower() == header_name.lower())
            try:
                quota_info[key] = int(headers[actual_key])
            except (ValueError, TypeError):
                quota_info[key] = None

    return quota_info


def update_quota_store(quota_info: Dict, model: str):
    """更新配额存储"""
    with quota_lock:
        changes = {}
        if quota_store["user_remaining"] is not None and quota_info.get("user_remaining") is not None:
            changes["user_used"] = quota_store["user_remaining"] - quota_info["user_remaining"]
        if quota_store["model_remaining"] is not None and quota_info.get("model_remaining") is not None:
            changes["model_used"] = quota_store["model_remaining"] - quota_info["model_remaining"]

        quota_store.update(quota_info)
        quota_store["last_model"] = model
        quota_store["last_update"] = datetime.now().isoformat()

        history_entry = {
            "timestamp": quota_store["last_update"],
            "model": model,
            "user_remaining": quota_info.get("user_remaining"),
            "model_remaining": quota_info.get("model_remaining")
        }
        quota_store["history"].append(history_entry)
        if len(quota_store["history"]) > 100:
            quota_store["history"] = quota_store["history"][-100:]

    return changes


def print_quota_info(quota_info: Dict, model: str, tier: str, changes: Dict = None):
    """打印配额信息到控制台"""
    prefix = f"[{tier.upper()}]" if tier != "direct" else ""

    print("\n" + "=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] API 调用完成 {prefix}")
    print(f"模型：{model}")
    print("-" * 60)

    if quota_info.get("user_limit") is not None:
        print(f"用户配额：{quota_info.get('user_remaining', 'N/A')}/{quota_info['user_limit']}")
        if changes and "user_used" in changes:
            print(f"  ↳ 本次消耗：{changes['user_used']}")

    if quota_info.get("model_limit") is not None:
        print(f"模型配额：{quota_info.get('model_remaining', 'N/A')}/{quota_info['model_limit']}")
        if changes and "model_used" in changes:
            print(f"  ↳ 本次消耗：{changes['model_used']}")

    try:
        if quota_info.get("user_limit") and quota_info.get("user_remaining") is not None:
            user_used = quota_info['user_limit'] - quota_info['user_remaining']
            user_percent = (user_used / quota_info['user_limit']) * 100
            print(f"用户使用比例：{user_percent:.1f}% ({user_used}/{quota_info['user_limit']})")

        if quota_info.get("model_limit") and quota_info.get("model_remaining") is not None:
            model_used = quota_info['model_limit'] - quota_info['model_remaining']
            model_percent = (model_used / quota_info['model_limit']) * 100
            print(f"模型使用比例：{model_percent:.1f}% ({model_used}/{quota_info['model_limit']})")
    except (ValueError, ZeroDivisionError):
        pass

    print("=" * 60 + "\n")


def send_request_to_model(model: str, api_key: str, request_data: dict, retry_count: int = 0) -> Tuple[Optional[Response], Optional[str]]:
    """
    发送请求到指定模型
    返回：(response, error_reason)
    """
    try:
        target_url = f"{get_base_url()}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # 替换请求中的 model 字段
        request_data = request_data.copy()
        request_data["model"] = model

        response = requests.post(
            target_url,
            headers=headers,
            json=request_data,
            stream=True,
            timeout=120
        )

        return response, None

    except Exception as e:
        logger.error(f"请求模型 {model} 失败：{str(e)}")
        return None, str(e)


def proxy_request_with_fallback(target_url: str, api_key: str):
    """代理请求，支持 429 自动降级重试"""
    try:
        request_data = request.get_json()
        original_model = request_data.get("model", "unknown") if request_data else "unknown"

        # 根据请求的 model 选择实际模型
        actual_model, tier_used = select_model_for_request(original_model)

        # 如果是 direct 模式，直接使用 original_model
        if tier_used == "direct":
            actual_model = original_model

        fallback_order = get_fallback_order()

        # 找到当前 tier 在 fallback_order 中的位置
        current_tier_index = fallback_order.index(tier_used) if tier_used in fallback_order else 0

        # 尝试所有可能的 tier（从当前 tier 开始降档）
        for tier_idx in range(current_tier_index, len(fallback_order)):
            next_tier = fallback_order[tier_idx]
            models_to_try = get_models_for_tier(next_tier)

            # 标记已尝试的模型，避免重复
            tried_models = set()

            for model in models_to_try:
                if model in tried_models:
                    continue
                tried_models.add(model)

                # 为当前模型设置独立的重试计数器
                model_retry_count = 0
                max_retries = 3

                while model_retry_count < max_retries:
                    logger.info(f"尝试模型：{model} (tier: {next_tier}, 重试 {model_retry_count}/{max_retries})")

                    response, error = send_request_to_model(actual_model if tier_used != "direct" else model, api_key, request_data)

                    if error:
                        logger.warning(f"模型 {model} 请求错误：{error}")
                        break

                    # 检查响应状态
                    if response.status_code == 429:
                        # 提取配额信息判断是真耗尽还是请求过频
                        quota_info = extract_quota_from_headers(response.headers)
                        model_remaining = quota_info.get('model_remaining', 0)

                        if model_remaining > 0:
                            # 请求过频，指数退避重试
                            retry_delay = min(2 ** model_retry_count, 10)  # 最大10秒
                            logger.warning(f"⚠️ 模型 {model} 请求过频 (429)，剩余配额 {model_remaining}，等待 {retry_delay} 秒重试 ({model_retry_count+1}/{max_retries})")
                            time.sleep(retry_delay)
                            model_retry_count += 1
                            continue  # 重试当前模型

                        # 配额耗尽
                        logger.warning(f"⚠️ 模型 {model} 配额耗尽 (429)，剩余配额 {model_remaining}，切换到其他模型...")
                        break  # 跳出重试循环，尝试下一个模型

                    if response.status_code >= 500:
                        logger.warning(f"模型 {model} 服务器错误 ({response.status_code})，重试中...")
                        model_retry_count += 1
                        time.sleep(min(2 ** model_retry_count, 5))
                        continue

                    # 成功！处理响应
                    quota_info = extract_quota_from_headers(response.headers)
                    if quota_info:
                        changes = update_quota_store(quota_info, model)
                        print_quota_info(quota_info, model, next_tier, changes)

                    excluded_response_headers = ["Content-Encoding", "Transfer-Encoding", "Connection"]
                    response_headers = [
                        (key, value) for key, value in response.headers.items()
                        if key not in excluded_response_headers
                    ]

                    return Response(
                        response.iter_content(chunk_size=8192),
                        status=response.status_code,
                        headers=response_headers
                    )

            # 如果当前 tier 的所有模型都尝试过了，继续下一个 tier（降档）
            if tier_idx < len(fallback_order) - 1:
                logger.error(f"❌ Tier '{fallback_order[tier_idx]}' 所有模型均已耗尽，降档到 '{fallback_order[tier_idx + 1]}' ...")

        # 所有 tier 都尝试失败了
        logger.error(f"💥 所有模型均已耗尽，无法完成请求!")
        return jsonify({"error": "All models exhausted. Please try again later."}), 503

    except Exception as e:
        logger.error(f"代理请求失败：{str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """聊天完成接口代理 - 支持 tier 智能路由"""
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "") or get_api_key()
    return proxy_request_with_fallback(get_base_url(), api_key)


@app.route('/v1/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy_v1(path):
    """代理所有 /v1/* 路径的请求"""
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "") or get_api_key()
    target_url = f"{get_base_url()}/{path}"

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        if request.method == "GET":
            response = requests.get(target_url, headers=headers, params=request.args, timeout=30)
        elif request.method == "POST":
            response = requests.post(target_url, headers=headers, json=request.get_json(), timeout=30)
        elif request.method == "PUT":
            response = requests.put(target_url, headers=headers, json=request.get_json(), timeout=30)
        elif request.method == "DELETE":
            response = requests.delete(target_url, headers=headers, timeout=30)
        else:
            return jsonify({"error": "Unsupported method"}), 405

        return Response(response.content, status=response.status_code, headers=dict(response.headers))

    except Exception as e:
        logger.error(f"代理请求失败：{str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/quota', methods=['GET'])
def get_quota():
    """获取当前配额信息"""
    with quota_lock:
        quota_info = {
            "user_limit": quota_store["user_limit"],
            "user_remaining": quota_store["user_remaining"],
            "model_limit": quota_store["model_limit"],
            "model_remaining": quota_store["model_remaining"],
            "last_model": quota_store["last_model"],
            "last_update": quota_store["last_update"]
        }

        if quota_info["user_limit"] and quota_info["user_remaining"] is not None:
            quota_info["user_used"] = quota_info["user_limit"] - quota_info["user_remaining"]
            quota_info["user_percent"] = round((quota_info["user_used"] / quota_info["user_limit"]) * 100, 2)

        if quota_info["model_limit"] and quota_info["model_remaining"] is not None:
            quota_info["model_used"] = quota_info["model_limit"] - quota_info["model_remaining"]
            quota_info["model_percent"] = round((quota_info["model_used"] / quota_info["model_limit"]) * 100, 2)

    return jsonify(quota_info)


@app.route('/quota/history', methods=['GET'])
def get_quota_history():
    """获取配额历史记录"""
    with quota_lock:
        return jsonify({
            "history": quota_store["history"][-20:],
            "total": len(quota_store["history"])
        })


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({"status": "ok", "service": "modelscope-proxy"})


@app.route('/tiers', methods=['GET'])
def get_tiers():
    """获取当前配置的 tier 信息"""
    config = load_tier_config()
    if not config:
        return jsonify({"error": "Failed to load config"}), 500
    return jsonify(config)


def main():
    """启动代理服务"""
    base_url = get_base_url()
    print("\n" + "=" * 60)
    print("ModelScope API 代理服务启动 (智能路由版)")
    print("=" * 60)
    print(f"代理地址：http://localhost:{PROXY_PORT}")
    print(f"目标 API: {base_url}")
    print(f"配额查询：http://localhost:{PROXY_PORT}/quota")
    print(f"历史记录：http://localhost:{PROXY_PORT}/quota/history")
    print(f"Tier 配置：http://localhost:{PROXY_PORT}/tiers")
    print(f"健康检查：http://localhost:{PROXY_PORT}/health")
    print("-" * 60)

    config = load_tier_config()
    if config:
        print("已配置的 Tiers:")
        for tier_name, tier_info in config.get("tiers", {}).items():
            models = tier_info.get("models", [])
            print(f"  {tier_name.upper()}: {', '.join(models)}")
    print("=" * 60 + "\n")

    app.run(
        host='0.0.0.0',
        port=PROXY_PORT,
        debug=False,
        threaded=True
    )


if __name__ == "__main__":
    main()
