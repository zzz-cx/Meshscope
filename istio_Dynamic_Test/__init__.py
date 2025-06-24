import os
import paramiko
from scp import SCPClient

REMOTE_HOST = "192.168.92.131"
REMOTE_USER = "root"
REMOTE_PASS = "12345678"
REMOTE_BASE = "/root/istio_Dynamic_Test"
REMOTE_SCRIPTS = f"{REMOTE_BASE}/scripts"
REMOTE_RESULTS = f"{REMOTE_BASE}/results"
LOCAL_BASE = os.path.dirname(__file__)

def ssh_client():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASS)
    return ssh

def ensure_remote_dirs():
    ssh = ssh_client()
    cmds = [
        f"mkdir -p {REMOTE_SCRIPTS}",
        f"mkdir -p {REMOTE_RESULTS}"
    ]
    for cmd in cmds:
        ssh.exec_command(cmd)
    ssh.close()

def sync_scripts_to_remote():
    ssh = ssh_client()
    with SCPClient(ssh.get_transport()) as scp:
        scp.put(os.path.join(LOCAL_BASE, "scripts"), recursive=True, remote_path=REMOTE_BASE)
    ssh.close()

def run_remote_script(script, *args):
    ssh = ssh_client()
    remote_cmd = f"cd {REMOTE_SCRIPTS} && bash {script} {' '.join(args)}"
    print(f"远程执行: {remote_cmd}")
    stdin, stdout, stderr = ssh.exec_command(remote_cmd)
    print(stdout.read().decode())
    print(stderr.read().decode())
    ssh.close()

def fetch_results_from_remote(pattern="*"):
    ssh = ssh_client()
    local_results = os.path.join(LOCAL_BASE, "results")
    os.makedirs(local_results, exist_ok=True)
    # 先列出所有匹配文件
    stdin, stdout, stderr = ssh.exec_command(f'ls {REMOTE_RESULTS}/{pattern}')
    files = [line.strip() for line in stdout if line.strip()]
    if not files:
        print("未找到匹配的结果文件")
        return
    with SCPClient(ssh.get_transport()) as scp:
        for f in files:
            print(f"拉取远程文件: {f}")
            scp.get(f, local_results)
    ssh.close()

def main():
    ensure_remote_dirs()
    sync_scripts_to_remote()
    print("步骤 1：复合匹配请求")
    run_remote_script('route_match.sh', '/v1', 'x-user', 'admin')
    fetch_results_from_remote("route_match_*.log")

    print("\n步骤 2：循环请求（验证分流+负载均衡+延迟注入）")
    # 参数：service_url, grep_pattern, weights, namespace, pod_name, Z, E
    run_remote_script(
        'weight_split.sh',
        'http://productpage:9080/productpage',
        'reviews-v[0-9]',
        '70,30',
        'default',
        'sleep-7656cf8794-p4422',  # 请替换为实际Pod名
        '1.96',
        '0.05'
    )
    fetch_results_from_remote("weight_split_*.log")

    print("\n步骤 3：并发压测（验证限流+熔断+重试策略）")
    run_remote_script('ratelimit.sh', 'http://productpage:9080/productpage', '100', '20')
    run_remote_script('circuit_breaker.sh', 'http://reviews:9080/', '100', '20')
    fetch_results_from_remote("ratelimit_*.log")
    fetch_results_from_remote("circuit_breaker_*.log")

    print("\n步骤 4：构造延迟接口（验证timeout+熔断+重试fallback）")
    run_remote_script('timeout.sh', 'http://service:9080/api', '1000')
    fetch_results_from_remote("timeout_*.log")

if __name__ == "__main__":
    main()
