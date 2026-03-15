#!/bin/bash

# Free API Forwarder 一键安装脚本
# 用法: curl -fsSL https://raw.githubusercontent.com/myrzx/free-api-forwarder/master/setup.sh | bash
# 或者: ./setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Free API Forwarder 安装脚本${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    else
        echo "unknown"
    fi
}

OS=$(detect_os)
SHELL_RC=""

# 检测 shell 配置文件
detect_shell_rc() {
    if [[ -n "$ZSH_VERSION" ]]; then
        SHELL_RC="$HOME/.zshrc"
    elif [[ -n "$BASH_VERSION" ]]; then
        SHELL_RC="$HOME/.bashrc"
    else
        SHELL_RC="$HOME/.profile"
    fi
}

detect_shell_rc

# 步骤 1: 检查 Python
echo -e "${YELLOW}[1/5] 检查 Python 环境...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}错误: 未找到 Python，请先安装 Python 3.x${NC}"
    exit 1
fi
echo -e "${GREEN}✓ 找到 Python: $($PYTHON_CMD --version)${NC}"
echo ""

# 步骤 2: 检查 API Key
echo -e "${YELLOW}[2/5] 检查 ModelScope API Key...${NC}"

if [[ -n "$MODELSCOPE_API_KEY" ]]; then
    echo -e "${GREEN}✓ 已检测到环境变量 MODELSCOPE_API_KEY${NC}"
    API_KEY="$MODELSCOPE_API_KEY"
else
    echo -e "${YELLOW}未检测到环境变量 MODELSCOPE_API_KEY${NC}"
    echo ""
    echo "请输入你的 ModelScope API Key:"
    echo "  - 获取方式: https://modelscope.cn/ → 个人中心 → 访问令牌"
    echo "  - 格式类似: ms-xxxxx"
    echo ""
    read -p "API Key: " API_KEY

    if [[ -z "$API_KEY" ]]; then
        echo -e "${RED}错误: API Key 不能为空${NC}"
        exit 1
    fi

    # 写入 shell 配置文件
    echo "" >> "$SHELL_RC"
    echo "# ModelScope API Key (added by free-api-forwarder)" >> "$SHELL_RC"
    echo "export MODELSCOPE_API_KEY=\"$API_KEY\"" >> "$SHELL_RC"
    export MODELSCOPE_API_KEY="$API_KEY"
    echo -e "${GREEN}✓ 已写入 $SHELL_RC${NC}"
    echo -e "${YELLOW}  提示: 运行 'source $SHELL_RC' 或重新打开终端生效${NC}"
fi
echo ""

# 步骤 3: 克隆或更新仓库
echo -e "${YELLOW}[3/5] 获取代码...${NC}"
INSTALL_DIR="$HOME/free-api-forwarder"

if [[ -d "$INSTALL_DIR" ]]; then
    echo -e "${YELLOW}目录已存在，正在更新...${NC}"
    cd "$INSTALL_DIR"
    git pull
else
    echo "正在克隆仓库..."
    git clone https://github.com/myrzx/free-api-forwarder.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
echo -e "${GREEN}✓ 代码已就绪${NC}"
echo ""

# 步骤 4: 安装依赖
echo -e "${YELLOW}[4/5] 安装 Python 依赖...${NC}"
$PYTHON_CMD -m pip install -r requirements.txt -q
echo -e "${GREEN}✓ 依赖安装完成${NC}"
echo ""

# 步骤 5: 配置文件
echo -e "${YELLOW}[5/5] 配置文件...${NC}"
CONFIG_FILE="config/tier-config.json"

# 更新配置文件中的 api_key（如果环境变量中有）
if [[ -n "$MODELSCOPE_API_KEY" ]]; then
    # 使用 sed 替换（兼容 macOS 和 Linux）
    if [[ "$OS" == "macos" ]]; then
        sed -i '' "s/YOUR_API_KEY_HERE/$MODELSCOPE_API_KEY/g" "$CONFIG_FILE"
    else
        sed -i "s/YOUR_API_KEY_HERE/$MODELSCOPE_API_KEY/g" "$CONFIG_FILE"
    fi
    echo -e "${GREEN}✓ 配置文件已更新${NC}"
else
    echo -e "${YELLOW}! 请手动编辑 $INSTALL_DIR/$CONFIG_FILE 填入 API Key${NC}"
fi
echo ""

# 完成
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   安装完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "启动服务:"
echo -e "  ${YELLOW}cd $INSTALL_DIR${NC}"
echo -e "  ${YELLOW}$PYTHON_CMD src/modelscope_proxy.py${NC}"
echo ""
echo "服务地址: http://localhost:8080"
echo ""
echo "更多使用方法请查看 README.md"