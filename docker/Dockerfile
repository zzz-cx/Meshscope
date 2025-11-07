# MeshScope - Istio 配置验证系统 Docker 镜像
# 支持执行项目中的所有可执行文件

FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    curl \
    git \
    ssh \
    sshpass \
    graphviz \
    ca-certificates \
    gnupg \
    vim \
    && rm -rf /var/lib/apt/lists/*

# 安装 kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl && \
    kubectl version --client

# 复制依赖文件（context 已设置为项目根目录）
COPY requirements.txt /app/

# 安装 Python 依赖
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 复制整个项目（.dockerignore 会排除不需要的文件）
COPY . /app/

# 创建必要的目录
RUN mkdir -p /app/results/{e2e_validation,consistency,visualization,envoy_logs,http_results,accuracy,performance,scalability} && \
    mkdir -p /app/istio_config_parser/istio_monitor/{istio_control_config,istio_sidecar_config} && \
    chmod -R 755 /app/results

# 复制入口脚本（从 docker 目录）
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 设置 Python 路径
ENV PYTHONPATH=/app:$PYTHONPATH

# 暴露端口（用于Web服务）
EXPOSE 8080 5000

# 设置入口点
ENTRYPOINT ["/app/entrypoint.sh"]

# 设置默认命令
CMD ["help"]
