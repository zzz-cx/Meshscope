import sys
import os
# 添加项目路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# 添加 istio_Dynamic_Test 路径
dynamic_test_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if dynamic_test_root not in sys.path:
    sys.path.insert(0, dynamic_test_root)

from istio_Dynamic_Test.utils.pod_log_utils import PodLogFetcher
from istio_Dynamic_Test.utils.envoy_log_utils import EnvoyLogEnabler

class EnvoyLogCollector:
    def __init__(self, ssh_client=None, namespace='default', result_dir='results/envoy_logs'):
        self.ssh_client = ssh_client
        self.namespace = namespace
        self.result_dir = result_dir
        os.makedirs(self.result_dir, exist_ok=True)

    def ensure_envoy_access_log(self, deployment, skip_if_enabled=True):
        # 直接调用 EnvoyLogEnabler，自动 patch+rollout restart+等待，传递 ssh_client
        # EnvoyLogEnabler 会自动检测环境
        EnvoyLogEnabler.enable_envoy_access_log(deployment, ssh_client=self.ssh_client, namespace=self.namespace, skip_if_enabled=skip_if_enabled)

    def collect_envoy_logs(self, case_id, service, subset=None, tail_lines=100, deployment=None):
        """
        采集目标服务/版本 pod 的 istio-proxy 容器访问日志，并保存到 results/envoy_logs 目录。
        自动检测环境：如果在 K8s 环境中直接执行，否则使用 SSH。
        :param case_id: 用例编号
        :param service: 目标服务名（如 reviews）
        :param subset: 目标版本（如 v2），可为 None
        :param tail_lines: 日志行数
        :param deployment: 可选参数，如传入则自动 patch+重启
        :return: {pod_name: log_str}
        """
        if deployment:
            self.ensure_envoy_access_log(deployment)
        if subset:
            label_selector = f"app={service},version={subset}"
            file_prefix = f"{case_id}_{service}_v{subset}"
        else:
            label_selector = f"app={service}"
            file_prefix = f"{case_id}_{service}"
        
        # PodLogFetcher 会自动检测环境
        pods = PodLogFetcher.get_pods_by_label(label_selector, namespace=self.namespace, ssh_client=self.ssh_client)
        logs = {}
        for pod in pods:
            try:
                log = PodLogFetcher.get_pod_logs(pod, namespace=self.namespace, container="istio-proxy", tail_lines=tail_lines, ssh_client=self.ssh_client)
                logs[pod] = log
                # 保存到文件
                with open(os.path.join(self.result_dir, f"{file_prefix}_{pod}.log"), 'w', encoding='utf-8') as f:
                    f.write(log)
            except Exception as e:
                logs[pod] = f"[ERROR] {e}"
        return logs

    def collect_gateway_logs(self, case_id, tail_lines=200):
        """
        收集Istio Gateway的访问日志，可能包含故障注入的503错误
        自动检测环境：如果在 K8s 环境中直接执行，否则使用 SSH。
        :param case_id: 用例编号
        :param tail_lines: 日志行数
        """
        try:
            # 获取istio-system命名空间中的istio-proxy (gateway) pods
            # 更准确的selector来找到gateway pods
            label_selector = "istio=ingressgateway"
            gateway_namespace = "istio-system"
            
            # PodLogFetcher 会自动检测环境
            pods = PodLogFetcher.get_pods_by_label(
                label_selector, namespace=gateway_namespace, ssh_client=self.ssh_client
            )
            
            for pod in pods:
                try:
                    log = PodLogFetcher.get_pod_logs(
                        pod, 
                        namespace=gateway_namespace, 
                        container="istio-proxy", 
                        tail_lines=tail_lines,
                        ssh_client=self.ssh_client
                    )
                    # 保存Gateway日志到单独的文件
                    filename = f"{case_id}_gateway_{pod}.log"
                    filepath = os.path.join(self.result_dir, filename)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(log)
                    print(f"    💾 Gateway日志已保存: {filename}")
                except Exception as e:
                    print(f"    ⚠️ 警告: 无法收集pod {pod}的Gateway日志: {e}")
                    
        except Exception as e:
            print(f"    ⚠️ 警告: 无法获取Gateway pods: {e}")