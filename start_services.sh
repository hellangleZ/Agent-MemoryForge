#!/bin/bash

# =================================
# 记忆驱动型AI Agent - 一键启动脚本
# =================================

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

get_primary_ip() {
    if command -v hostname &> /dev/null; then
        hostname -I 2>/dev/null | awk '{print $1}'
        return 0
    fi
    echo "127.0.0.1"
}

is_truthy() {
    local val="${1:-}"
    val="$(echo "$val" | tr '[:upper:]' '[:lower:]' | xargs)"
    [[ "$val" == "1" || "$val" == "true" || "$val" == "yes" || "$val" == "y" || "$val" == "on" ]]
}

distill_enabled() {
    is_truthy "${MEMORY_DISTILL_ENABLED:-0}"
}

graph_enabled() {
    is_truthy "${AGENT_MEMORY_GRAPH_ENABLED:-0}"
}

pid_from_port() {
    local port="$1"
    if command -v fuser &> /dev/null; then
        # fuser prints one or more PIDs; take the first.
        fuser -n tcp "${port}" 2>/dev/null | awk '{print $1}' | head -n 1
    elif command -v ss &> /dev/null; then
        ss -H -tlnp 2>/dev/null \
            | awk -v port="${port}" '$4 ~ ":"port"$" {print $NF}' \
            | sed -n 's/.*pid=\\([0-9]\\+\\).*/\\1/p' \
            | head -n 1
    elif command -v lsof &> /dev/null; then
        lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | head -n 1
    elif command -v netstat &> /dev/null; then
        netstat -tlnp 2>/dev/null \
            | awk -v port="${port}" '$4 ~ ":"port"$" {print $7}' \
            | sed -n 's#\\([0-9]\\+\\)/.*#\\1#p' \
            | head -n 1
    else
        echo ""
    fi
}

kill_pid_best_effort() {
    local pid="$1"
    if [ -z "${pid}" ]; then
        return
    fi
    if ! kill -0 "${pid}" 2>/dev/null; then
        return
    fi
    kill "${pid}" 2>/dev/null || true
    # Give it a moment, then force kill if still alive.
    sleep 0.3
    if kill -0 "${pid}" 2>/dev/null; then
        kill -9 "${pid}" 2>/dev/null || true
    fi
}

wait_pid_from_port() {
    local port="$1"
    local attempts="${2:-30}"
    local sleep_s="${3:-0.1}"
    local pid=""
    for _ in $(seq 1 "${attempts}"); do
        pid="$(pid_from_port "${port}")"
        if [ -n "${pid}" ]; then
            echo "${pid}"
            return 0
        fi
        sleep "${sleep_s}"
    done
    echo ""
}

# 检查基本环境
check_dependencies() {
    log_info "检查基本环境..."
    
    # 检查必要命令是否存在
    local missing_commands=()
    
    # docker/neo4j are optional; memory+gateway only require python3/curl.
    for cmd in python3 curl; do
        if ! command -v $cmd &> /dev/null; then
            missing_commands+=($cmd)
        fi
    done

    # Only require docker if we intend to start dockerized Redis.
    if is_truthy "${START_REDIS:-0}" && ! check_port 6379; then
        if ! command -v docker &> /dev/null; then
            missing_commands+=(docker)
        fi
    fi
    
    if [ ${#missing_commands[@]} -ne 0 ]; then
        log_error "缺少必要命令: ${missing_commands[*]}"
        log_error "请确保已安装 Python3 和 curl（如需 Docker Redis，则还需要 Docker）"
        exit 1
    fi
    
    # 检查Neo4j是否运行
    if graph_enabled && ! check_port 7687; then
        log_warning "Neo4j 未在本地运行 (localhost:7687)"
        log_warning "请确保 Neo4j 服务已启动"
    fi
    
    log_success "环境检查完成"
}

# Load .env if present (do not fail if missing)
load_dotenv() {
    if [ -f ".env" ]; then
        log_info "加载 .env 环境变量..."
        set -a
        # shellcheck disable=SC1091
        source .env
        set +a
        log_success ".env 已加载"
    fi
}

# 检查端口是否被占用
check_port() {
    local port=$1
    if command -v nc &> /dev/null; then
        nc -z localhost $port &> /dev/null
    elif command -v netcat &> /dev/null; then
        netcat -z localhost $port &> /dev/null
    else
        # 备用方法：使用 ss 或 netstat
        if command -v ss &> /dev/null; then
            ss -ln | grep ":$port " &> /dev/null
        elif command -v netstat &> /dev/null; then
            netstat -ln | grep ":$port " &> /dev/null
        else
            # 最后备用：尝试连接
            timeout 1 bash -c "</dev/tcp/localhost/$port" &> /dev/null
        fi
    fi
}

# 启动Redis Docker
start_redis() {
    log_info "启动 Redis Docker 容器..."

    # If Redis is already available on localhost:6379, don't try to run docker.
    if check_port 6379; then
        log_warning "检测到本地 Redis 已在运行 (localhost:6379)，跳过 Docker Redis"
        return
    fi

    # Redis is optional unless distill worker is enabled or explicitly requested.
    if ! distill_enabled && ! is_truthy "${START_REDIS:-0}"; then
        log_warning "Redis 仅在 distill 队列启用时需要 (MEMORY_DISTILL_ENABLED=1)。当前未启用，跳过启动 Redis"
        return
    fi
    
    # 检查Redis容器是否正在运行
    if sudo docker ps | grep -q "agent-redis"; then
        log_warning "Redis 容器已在运行"
        return
    fi
    
    # 检查容器是否存在但已停止
    if sudo docker ps -a | grep -q "agent-redis"; then
        log_info "发现已存在的 Redis 容器，正在启动..."
        sudo docker start agent-redis
        log_success "Redis 容器已启动"
    else
        log_warning "未找到名为 agent-redis 的 Docker 容器，正在创建..."
        sudo docker run -d --name agent-redis -p 6379:6379 redis:7-alpine
        log_success "Redis 容器已创建并启动"
    fi
    
    # 等待Redis启动
    log_info "等待 Redis 启动..."
    for i in {1..30}; do
        if sudo docker exec agent-redis redis-cli ping &> /dev/null 2>&1; then
            log_success "Redis 启动成功"
            break
        fi
        if [ $i -eq 30 ]; then
            log_error "Redis 启动超时"
            exit 1
        fi
        sleep 1
    done
}

# 启动Neo4j服务
start_neo4j() {
    log_info "启动 Neo4j 服务..."

    if ! graph_enabled && ! is_truthy "${START_NEO4J:-0}"; then
        log_warning "Neo4j 仅在图谱派生索引启用时需要 (AGENT_MEMORY_GRAPH_ENABLED=1)。当前未启用，跳过启动 Neo4j"
        return
    fi
    
    # 检查Neo4j服务状态
    if systemctl is-active --quiet neo4j; then
        log_warning "Neo4j 服务已在运行"
    else
        sudo systemctl start neo4j
        log_success "Neo4j 服务启动命令已执行"
    fi
    
    # 等待Neo4j启动
    log_info "等待 Neo4j 启动..."
    for i in {1..60}; do
        if check_port 7687; then
            log_success "Neo4j 启动成功"
            break
        fi
        if [ $i -eq 60 ]; then
            log_error "Neo4j 启动超时"
            exit 1
        fi
        sleep 2
    done
}

# 设置环境变量
setup_environment() {
    log_info "设置环境变量..."

    # Respect values from .env if present (loaded via load_dotenv).
    # Only set defaults when env vars are missing.
    
    # 确保conda python路径在PATH中
    export PATH="/home/root123/miniconda3/bin:$PATH"
    
    # 模型路径
    if [ -d "/aml/xiaowangge" ]; then
        export MODEL_PATH="/aml/xiaowangge"
        log_info "使用模型路径: $MODEL_PATH"
    elif [ -d "./xiaowangge" ]; then
        export MODEL_PATH="$(pwd)/xiaowangge"
        log_info "使用本地模型路径: $MODEL_PATH"
    elif [ -d "./models" ]; then
        export MODEL_PATH="$(pwd)/models"
        log_info "使用本地模型路径: $MODEL_PATH"
    else
        log_warning "未找到模型目录，请确保模型文件在 /aml/xiaowangge、./xiaowangge 或 ./models 目录下"
        export MODEL_PATH="${MODEL_PATH:-/aml/xiaowangge}"  # 默认使用绝对路径
        log_info "使用默认模型路径: $MODEL_PATH"
    fi
    
    # Redis连接信息
    export REDIS_HOST="${REDIS_HOST:-localhost}"
    export REDIS_PORT="${REDIS_PORT:-6379}"
    export REDIS_DB="${REDIS_DB:-0}"
    
    # Neo4j连接信息
    export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
    export NEO4J_USER="${NEO4J_USER:-neo4j}"
    export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"  # Neo4j密码
    
    # 嵌入服务URL (must include the endpoint path)
    export EMBEDDING_SERVICE_URL="${EMBEDDING_SERVICE_URL:-http://localhost:7999/v1/embeddings}"
    
    log_success "环境变量设置完成"
}

# 启动嵌入服务
start_embedding_service() {
    log_info "启动嵌入服务..."

    # If embeddings are not local, do not start the local embedding service.
    if [ "${EMBEDDING_PROVIDER:-local}" != "local" ]; then
        log_warning "EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER:-local}，跳过启动本地嵌入服务"
        return
    fi
    
    # 检查端口是否已被占用
    if check_port 7999; then
        EMBEDDING_PID="$(wait_pid_from_port 7999)"
        if [ -n "${EMBEDDING_PID}" ]; then
            echo "${EMBEDDING_PID}" > embedding_service.pid
        fi
        log_warning "端口 7999 已被占用，跳过启动嵌入服务 (PID: ${EMBEDDING_PID:-unknown})"
        return
    fi
    
    # 检查必要文件
    if [ ! -f "embedding_service.py" ]; then
        log_error "embedding_service.py 文件不存在"
        exit 1
    fi
    
    # 独立会话启动，避免父进程退出时被清理
    rm -f embedding_service.pid
    setsid -f python -m uvicorn embedding_service:app --host 0.0.0.0 --port 7999 > embedding_service.log 2>&1
    
    # 等待服务启动
    log_info "等待嵌入服务启动..."
    for i in {1..60}; do
        if curl -s http://localhost:7999/health | grep -q '"status":"healthy"'; then
            EMBEDDING_PID="$(wait_pid_from_port 7999)"
            if [ -n "${EMBEDDING_PID}" ]; then
                echo "${EMBEDDING_PID}" > embedding_service.pid
            fi
            log_success "嵌入服务启动成功 (PID: ${EMBEDDING_PID:-unknown})"
            break
        fi
        if [ $i -eq 60 ]; then
            log_error "嵌入服务启动超时"
            log_info "请检查日志: tail -f embedding_service.log"
            exit 1
        fi
        sleep 2
    done
}

# 启动记忆服务
start_memory_service() {
    log_info "启动记忆服务..."
    
    # 检查端口是否已被占用
    if check_port 8001; then
        MEMORY_PID="$(wait_pid_from_port 8001)"
        if [ -n "${MEMORY_PID}" ]; then
            echo "${MEMORY_PID}" > memory_service.pid
        fi
        log_warning "端口 8001 已被占用，跳过启动记忆服务 (PID: ${MEMORY_PID:-unknown})"
        return
    fi
    
	# 独立会话启动（避免父进程退出时被清理）
    rm -f memory_service.pid
	setsid -f python -m uvicorn agent_memory_service.app:create_app --factory --host 0.0.0.0 --port 8001 > memory_service.log 2>&1
    
    # 等待服务启动
    log_info "等待记忆服务启动..."
    for i in {1..60}; do
        if curl -s http://localhost:8001/health | grep -q '"status":"healthy"'; then
            MEMORY_PID="$(wait_pid_from_port 8001)"
            if [ -n "${MEMORY_PID}" ]; then
                echo "${MEMORY_PID}" > memory_service.pid
            fi
            log_success "记忆服务启动成功 (PID: ${MEMORY_PID:-unknown})"
            break
        fi
        if [ $i -eq 60 ]; then
            log_error "记忆服务启动超时"
            log_info "请检查日志: tail -f memory_service.log"
            exit 1
        fi
        sleep 2
    done
}



# 启动Gateway服务 (产品Portal + /v1/chat)
start_gateway_service() {
    log_info "启动 Gateway 服务..."

    # 默认 host/port
    local host="${AGENT_GATEWAY_HOST:-0.0.0.0}"
    local port="${AGENT_GATEWAY_PORT:-8080}"

    # 检查端口是否已被占用
    if check_port "${port}"; then
        GATEWAY_PID="$(wait_pid_from_port "${port}")"
        if [ -n "${GATEWAY_PID}" ]; then
            echo "${GATEWAY_PID}" > agent_gateway.pid
        fi
        log_warning "端口 ${port} 已被占用，跳过启动 Gateway (PID: ${GATEWAY_PID:-unknown})"
        return
    fi

    # 独立会话启动（避免父进程退出时被清理）
    rm -f agent_gateway.pid
    setsid -f env PYTHONUNBUFFERED=1 python -m uvicorn agent_runtime.product.agent_gateway:app --host "${host}" --port "${port}" --log-level info > agent_gateway.log 2>&1

    log_info "等待 Gateway 启动..."
    for i in {1..60}; do
        if curl -fsS "http://localhost:${port}/healthz" >/dev/null 2>&1; then
            GATEWAY_PID="$(wait_pid_from_port "${port}")"
            if [ -n "${GATEWAY_PID}" ]; then
                echo "${GATEWAY_PID}" > agent_gateway.pid
            fi
            log_success "Gateway 启动成功 (PID: ${GATEWAY_PID:-unknown})"
            break
        fi
        if [ $i -eq 60 ]; then
            log_error "Gateway 启动超时"
            log_info "请检查日志: tail -f agent_gateway.log"
            exit 1
        fi
        sleep 1
    done
}

# 启动Portal UI (Next.js dev server)
start_portal_ui() {
    log_info "启动 Portal UI..."

    local port="${PORTAL_UI_PORT:-3000}"
    local host="${PORTAL_UI_HOST:-0.0.0.0}"

    if check_port "${port}"; then
        UI_PID="$(wait_pid_from_port "${port}")"
        if [ -n "${UI_PID}" ]; then
            echo "${UI_PID}" > portal-ui/portal-ui.pid
        fi
        log_warning "端口 ${port} 已被占用，跳过启动 Portal UI (PID: ${UI_PID:-unknown})"
        return
    fi

    if [ ! -d "portal-ui" ]; then
        log_error "portal-ui 目录不存在"
        exit 1
    fi

    rm -f portal-ui/portal-ui.pid
    (cd portal-ui && setsid -f env HOST="${host}" PORT="${port}" npm run dev:custom > ../portal_ui.log 2>&1)

    log_info "等待 Portal UI 启动..."
    for i in {1..60}; do
        if curl -fsS "http://localhost:${port}/" >/dev/null 2>&1; then
            UI_PID="$(wait_pid_from_port "${port}")"
            if [ -n "${UI_PID}" ]; then
                echo "${UI_PID}" > portal-ui/portal-ui.pid
            fi
            log_success "Portal UI 启动成功 (PID: ${UI_PID:-unknown})"
            break
        fi
        if [ $i -eq 60 ]; then
            log_error "Portal UI 启动超时"
            log_info "请检查日志: tail -f portal_ui.log"
            exit 1
        fi
        sleep 1
    done
}
# 启动 Distill Worker (异步记忆蒸馏队列消费进程)
start_distill_worker() {
    log_info "启动 Distill Worker..."

    # 仅在蒸馏队列启用时需要
    if ! distill_enabled; then
        log_warning "Distill Worker 仅在蒸馏队列启用时需要 (MEMORY_DISTILL_ENABLED=1)。当前未启用，跳过启动"
        return
    fi

    # Worker 依赖 Redis 队列
    if ! check_port 6379; then
        log_error "Distill Worker 需要 Redis (localhost:6379)，但未检测到 Redis，跳过启动"
        log_info "可设置 START_REDIS=1 让脚本启动 Docker Redis，或先手动启动本地 Redis"
        return
    fi

    # 已在运行则跳过
    if [ -f "distill_worker.pid" ]; then
        local existing_pid
        existing_pid="$(cat distill_worker.pid 2>/dev/null)"
        if [ -n "${existing_pid}" ] && kill -0 "${existing_pid}" 2>/dev/null; then
            log_warning "Distill Worker 已在运行 (PID: ${existing_pid})，跳过启动"
            return
        fi
    fi

    if [ ! -f "scripts/memory_distill_worker.py" ]; then
        log_error "scripts/memory_distill_worker.py 文件不存在"
        return
    fi

    # 独立会话启动（避免父进程退出时被清理）。
    # 子进程先写入自身 PID，再 exec 成 worker，PID 保持不变。
    rm -f distill_worker.pid
    setsid bash -c 'echo $$ > distill_worker.pid; exec env PYTHONUNBUFFERED=1 PYTHONPATH="$(pwd)" python scripts/memory_distill_worker.py' > distill_worker.log 2>&1 &

    # 确认进程存活
    log_info "等待 Distill Worker 启动..."
    local pid=""
    for i in {1..15}; do
        if [ -f "distill_worker.pid" ]; then
            pid="$(cat distill_worker.pid 2>/dev/null)"
        fi
        # MEMORY_DISTILL_ENABLED 为假时 worker 会自行退出 (exit 2)
        if grep -q "MEMORY_DISTILL_ENABLED is false" distill_worker.log 2>/dev/null; then
            log_error "Distill Worker 因 MEMORY_DISTILL_ENABLED 为假而退出，请检查 .env"
            rm -f distill_worker.pid
            return
        fi
        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            log_success "Distill Worker 启动成功 (PID: ${pid})"
            return
        fi
        sleep 0.5
    done

    log_error "Distill Worker 启动失败或未能确认存活"
    log_info "请检查日志: tail -f distill_worker.log"
}

# 检查服务状态
check_services() {
    log_info "检查所有服务状态..."
    
    echo "======================================"
    echo "           服务状态检查"
    echo "======================================"
    
    # Redis
    if docker ps 2>/dev/null | grep -q "agent-redis"; then
        echo -e "Redis (Docker):     ${GREEN}✓ 运行中${NC} (localhost:6379)"
    elif check_port 6379; then
        echo -e "Redis (本地):       ${GREEN}✓ 运行中${NC} (localhost:6379)"
    else
        echo -e "Redis:              ${RED}✗ 未运行${NC}"
    fi
    
    # Neo4j
    if check_port 7687; then
        echo -e "Neo4j (本地):       ${GREEN}✓ 运行中${NC} (localhost:7687)"
    else
        echo -e "Neo4j (本地):       ${YELLOW}? 未检测到${NC} (localhost:7687)"
    fi
    
    # 嵌入服务
    EMB_PROVIDER="${EMBEDDING_PROVIDER:-local}"
    if [ "${EMB_PROVIDER}" != "local" ]; then
        echo -e "Embedding Provider: ${GREEN}${EMB_PROVIDER}${NC} (不需要本地 7999)"
    else
        if check_port 7999; then
            if [ -f "embedding_service.pid" ]; then
                PID=$(cat embedding_service.pid)
                if kill -0 $PID 2>/dev/null; then
                    echo -e "嵌入服务(本地):     ${GREEN}✓ 运行中${NC} (localhost:7999, PID: $PID)"
                else
                    echo -e "嵌入服务(本地):     ${YELLOW}? 端口占用但PID无效${NC} (localhost:7999)"
                fi
            else
                echo -e "嵌入服务(本地):     ${YELLOW}? 运行中但无PID文件${NC} (localhost:7999)"
            fi
        else
            echo -e "嵌入服务(本地):     ${RED}✗ 未运行${NC}"
        fi
    fi
    
    # 记忆服务
    if check_port 8001; then
        if [ -f "memory_service.pid" ]; then
            PID=$(cat memory_service.pid)
            if kill -0 $PID 2>/dev/null; then
                echo -e "记忆服务:           ${GREEN}✓ 运行中${NC} (localhost:8001, PID: $PID)"
            else
                echo -e "记忆服务:           ${YELLOW}? 端口占用但PID无效${NC} (localhost:8001)"
            fi
        else
            echo -e "记忆服务:           ${YELLOW}? 运行中但无PID文件${NC} (localhost:8001)"
        fi
    else
        echo -e "记忆服务:           ${RED}✗ 未运行${NC}"
    fi
    


    # Gateway
    GW_PORT="${AGENT_GATEWAY_PORT:-8080}"
    if check_port "${GW_PORT}"; then
        if [ -f "agent_gateway.pid" ]; then
            PID=$(cat agent_gateway.pid)
            if kill -0 $PID 2>/dev/null; then
                echo -e "Gateway:            ${GREEN}✓ 运行中${NC} (localhost:${GW_PORT}, PID: $PID)"
            else
                echo -e "Gateway:            ${YELLOW}? 端口占用但PID无效${NC} (localhost:${GW_PORT})"
            fi
        else
            echo -e "Gateway:            ${YELLOW}? 运行中但无PID文件${NC} (localhost:${GW_PORT})"
        fi
    else
        echo -e "Gateway:            ${RED}✗ 未运行${NC} (localhost:${GW_PORT})"
    fi
    echo "======================================"

    # Portal UI
    UI_PORT="${PORTAL_UI_PORT:-3000}"
    if check_port "${UI_PORT}"; then
        if [ -f "portal-ui/portal-ui.pid" ]; then
            PID=$(cat portal-ui/portal-ui.pid)
            if kill -0 $PID 2>/dev/null; then
                echo -e "Portal UI:          ${GREEN}✓ 运行中${NC} (localhost:${UI_PORT}, PID: $PID)"
            else
                echo -e "Portal UI:          ${YELLOW}? 端口占用但PID无效${NC} (localhost:${UI_PORT})"
            fi
        else
            echo -e "Portal UI:          ${YELLOW}? 运行中但无PID文件${NC} (localhost:${UI_PORT})"
        fi
    else
        echo -e "Portal UI:          ${RED}✗ 未运行${NC} (localhost:${UI_PORT})"
    fi

    # Distill Worker (无端口，基于 PID 文件 / 进程名判断)
    if distill_enabled; then
        DW_PID=""
        if [ -f "distill_worker.pid" ]; then
            DW_PID="$(cat distill_worker.pid 2>/dev/null)"
        fi
        if [ -n "${DW_PID}" ] && kill -0 "${DW_PID}" 2>/dev/null; then
            echo -e "Distill Worker:     ${GREEN}✓ 运行中${NC} (PID: ${DW_PID})"
        elif pgrep -f "memory_distill_worker.py" >/dev/null 2>&1; then
            RPID="$(pgrep -f 'memory_distill_worker.py' | head -n 1)"
            echo -e "Distill Worker:     ${YELLOW}? 运行中但PID文件失效${NC} (PID: ${RPID})"
        else
            echo -e "Distill Worker:     ${RED}✗ 未运行${NC}"
        fi
    else
        echo -e "Distill Worker:     ${YELLOW}- 未启用${NC} (MEMORY_DISTILL_ENABLED!=1)"
    fi
    
    # 显示端口占用情况
    echo ""
    echo "端口占用详情:"
    if command -v ss &> /dev/null; then
        ss -tlnp | grep -E ":(3000|6379|7687|7999|8001|8080) " | while read line; do
            echo "  $line"
        done
    elif command -v netstat &> /dev/null; then
        netstat -tlnp | grep -E ":(3000|6379|7687|7999|8001|8080) " | while read line; do
            echo "  $line"
        done
    fi
}

# 停止服务
stop_services() {
    log_info "停止所有服务..."

    # 停止 Distill Worker
    if [ -f "distill_worker.pid" ]; then
        PID=$(cat distill_worker.pid)
        kill_pid_best_effort "${PID}"
        log_success "Distill Worker 已停止"
        rm -f distill_worker.pid
    fi
    # Fallback: 清理任何残留的 worker 进程
    if command -v pgrep &> /dev/null; then
        DW_PIDS=$(pgrep -f "memory_distill_worker.py" 2>/dev/null || true)
        for P in $DW_PIDS; do
            kill_pid_best_effort "$P"
        done
    fi

    # 停止Portal UI
    if [ -f "portal-ui/portal-ui.pid" ]; then
        PID=$(cat portal-ui/portal-ui.pid)
        kill_pid_best_effort "${PID}"
        log_success "Portal UI 已停止"
        rm -f portal-ui/portal-ui.pid
    fi
    # Fallback: kill any process still holding the Portal UI port.
    UI_PORT="${PORTAL_UI_PORT:-3000}"
    UI_PID="$(pid_from_port "${UI_PORT}")"
    kill_pid_best_effort "${UI_PID}"

    # 停止Gateway
    if [ -f "agent_gateway.pid" ]; then
        PID=$(cat agent_gateway.pid)
        kill_pid_best_effort "${PID}"
        log_success "Gateway 已停止"
        rm -f agent_gateway.pid
    fi

    # Also stop any gateway process still holding port 8080 (stale/no pidfile cases)
    if command -v ss &> /dev/null; then
        PIDS=$(ss -H -tlnp 2>/dev/null | awk '$4 ~ /:8080$/ {print $NF}' | sed -n 's/.*pid=\\([0-9]\\+\\).*/\\1/p' | sort -u)
        for P in $PIDS; do
            kill_pid_best_effort "$P"
        done
    fi
    
    # 停止记忆服务
    if [ -f "memory_service.pid" ]; then
        PID=$(cat memory_service.pid)
        kill_pid_best_effort "${PID}"
        log_success "记忆服务已停止"
        rm -f memory_service.pid
    fi
    # Fallback: kill any process still holding port 8001.
    MEMORY_PID="$(pid_from_port 8001)"
    kill_pid_best_effort "${MEMORY_PID}"
    
    # 停止嵌入服务
    if [ -f "embedding_service.pid" ]; then
        PID=$(cat embedding_service.pid)
        kill_pid_best_effort "${PID}"
        log_success "嵌入服务已停止"
        rm -f embedding_service.pid
    fi
    # Fallback: kill any process still holding port 7999.
    EMBEDDING_PID="$(pid_from_port 7999)"
    kill_pid_best_effort "${EMBEDDING_PID}"
    
    # 停止Redis Docker
    if command -v docker &> /dev/null; then
        if sudo docker ps | grep -q "agent-redis"; then
            sudo docker stop agent-redis
            log_success "Redis Docker 已停止"
        fi
    fi
    
    # 停止Neo4j服务（可选，通常不需要停止系统服务）
    # sudo systemctl stop neo4j
    # log_info "Neo4j 服务已停止（如需要）"
}

# 注入测试数据
inject_test_data() {
    log_info "注入测试数据..."
    
    if [ -f "inject_massive_data.py" ]; then
        python3 inject_massive_data.py
        log_success "测试数据注入完成"
    else
        log_warning "inject_massive_data.py 文件不存在，跳过数据注入"
    fi
}

# 主函数
main() {
    case "${1:-start}" in
        "start")
            echo "========================================"
            echo "    记忆驱动型AI Agent - 服务启动"
            echo "========================================"
            
            check_dependencies
            load_dotenv
            start_redis
            start_neo4j
            setup_environment
            start_embedding_service
            start_memory_service
            start_gateway_service
            start_distill_worker
            start_portal_ui
            
            echo ""
            check_services
            
            echo ""
            log_success "所有服务启动完成！"

            # Provider health-check (non-fatal): surface misconfigured LLM/Embedding roles early.
            if ! is_truthy "${SKIP_PROVIDER_CHECK:-0}"; then
                if ! PYTHONPATH="$(pwd)" python scripts/check_providers.py; then
                    log_warning "部分 LLM/Embedding provider 体检未通过；详情运行: ./start_services.sh doctor"
                fi
            fi
            echo ""
            echo "接下来您可以："
            echo "1. 运行示例: python3 examples/project_management_demo_real.py"
            echo "2. 注入测试数据: ./start_services.sh inject"
            echo "3. 检查服务状态: ./start_services.sh status"
            echo "4. 停止所有服务: ./start_services.sh stop"
            echo ""
            IP=$(get_primary_ip)
            echo "访问地址 (LAN):"
            echo "  - Memory service: http://${IP}:8001/health"
            GW_PORT="${AGENT_GATEWAY_PORT:-8080}"
            echo "  - Gateway:       http://${IP}:${GW_PORT}/healthz"
            UI_PORT="${PORTAL_UI_PORT:-3000}"
            echo "  - Portal UI:     http://${IP}:${UI_PORT}/"
            echo ""
            ;;

        "portal")
            echo "========================================"
            echo "    记忆驱动型AI Agent - Portal UI 启动"
            echo "========================================"

            load_dotenv
            start_portal_ui
            ;;

        "gateway")
            echo "========================================"
            echo "    记忆驱动型AI Agent - Gateway 启动"
            echo "========================================"

            check_dependencies
            load_dotenv

            # Default to 0.0.0.0 for LAN access.
            HOST="${AGENT_GATEWAY_HOST:-0.0.0.0}"
            PORT="${AGENT_GATEWAY_PORT:-8080}"
            log_info "启动 Gateway: ${HOST}:${PORT}"
            IP=$(get_primary_ip)
            log_info "Health: http://${IP}:${PORT}/healthz"
            python -m uvicorn agent_runtime.product.agent_gateway:app --host "${HOST}" --port "${PORT}"
            ;;

        "distill")
            echo "========================================"
            echo "    记忆驱动型AI Agent - Distill Worker 启动"
            echo "========================================"

            check_dependencies
            load_dotenv
            setup_environment
            start_redis
            start_distill_worker
            ;;
            
        "doctor")
            echo "========================================"
            echo "    记忆驱动型AI Agent - Provider 体检"
            echo "========================================"
            load_dotenv
            setup_environment
            PYTHONPATH="$(pwd)" python scripts/check_providers.py
            ;;

        "stop")
            echo "========================================"
            echo "    记忆驱动型AI Agent - 服务停止"
            echo "========================================"
            stop_services
            ;;
            
        "restart")
            echo "========================================"
            echo "    记忆驱动型AI Agent - 服务重启"
            echo "========================================"
            stop_services
            sleep 2
            main start
            ;;
            
        "status")
            load_dotenv
            check_services
            ;;
            
        "inject")
            inject_test_data
            ;;
            
        "logs")
            echo "========================================"
            echo "           服务日志查看"
            echo "========================================"
            echo ""
            echo "Redis 日志:"
            docker logs agent-redis --tail 20
            echo ""
            echo "嵌入服务日志:"
            if [ -f "embedding_service.log" ]; then
                tail -20 embedding_service.log
            else
                echo "日志文件不存在"
            fi
            echo ""
            echo "记忆服务日志:"
            if [ -f "memory_service.log" ]; then
                tail -20 memory_service.log
            else
                echo "日志文件不存在"
            fi
            echo ""
            echo "Distill Worker 日志:"
            if [ -f "distill_worker.log" ]; then
                tail -20 distill_worker.log
            else
                echo "日志文件不存在"
            fi
            ;;
            
        "sysinfo")
            echo "========================================"
            echo "           系统信息"
            echo "========================================"
            echo "操作系统: $(uname -s) $(uname -r)"
            echo "架构: $(uname -m)"
            if [ -f /etc/os-release ]; then
                echo "发行版: $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"')"
            fi
            echo "Python版本: $(python3 --version)"
            echo "Docker版本: $(docker --version)"
            if command -v docker-compose &> /dev/null; then
                echo "Docker Compose版本: $(docker-compose --version)"
            fi
            echo ""
            echo "内存使用:"
            free -h
            echo ""
            echo "磁盘使用:"
            df -h .
            echo ""
            ;;
            
        "help"|"--help"|"-h")
            echo "记忆驱动型AI Agent - 服务管理脚本 (Linux版)"
            echo ""
            echo "用法: $0 [命令]"
            echo ""
            echo "命令:"
            echo "  start    启动核心服务 + Portal UI (默认)"
            echo "  portal   仅启动 Portal UI (localhost:3000)"
            echo "  gateway  启动产品 Gateway (0.0.0.0:8080)"
            echo "  distill  仅启动 Distill Worker (异步蒸馏队列消费)"
            echo "  doctor   检查各 LLM/Embedding provider 连通性"
            echo "  stop     停止所有服务"
            echo "  restart  重启所有服务"
            echo "  status   检查服务状态"
            echo "  inject   注入测试数据"
            echo "  logs     查看服务日志"
            echo "  sysinfo  显示系统信息"
            echo "  help     显示此帮助信息"
            echo ""
            echo "服务架构:"
            echo "  - Redis: 可选 (distill 队列启用时需要；或 START_REDIS=1)"
            echo "  - Neo4j: 可选 (图谱派生索引启用时需要；或 START_NEO4J=1)"
            echo "  - 嵌入服务: 可选 (EMBEDDING_PROVIDER=local 时本地启动 7999)"
            echo "  - 记忆服务: Python本地运行 (localhost:8001)
  - Gateway: 产品Portal + Chat API (localhost:8080)"
            echo "  - Portal UI: Next.js dev (localhost:3000)"
            echo "  - Distill Worker: 异步蒸馏队列消费 (需 MEMORY_DISTILL_ENABLED=1 + Redis)"
            echo ""
            echo "前置要求:"
            echo "  - Docker 和 Docker Compose 已安装"
            echo "  - Neo4j 服务已安装并运行"
            echo "  - Python3 环境已配置"
            echo "  - SQLite 已安装"
            echo ""
            ;;
            
        *)
            log_error "未知命令: $1"
            echo "使用 '$0 help' 查看可用命令"
            exit 1
            ;;
    esac
}

# 捕获中断信号
trap 'echo ""; log_info "收到中断信号，正在停止服务..."; stop_services; exit 0' INT TERM

# 执行主函数
main "$@"
