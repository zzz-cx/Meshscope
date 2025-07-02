from istio_Dynamic_Test.utils.prometheus_utils import PrometheusClient
import os
import json

class PrometheusCollector:
    def __init__(self, prometheus_url, result_dir='results/prometheus'):
        self.client = PrometheusClient(prometheus_url)
        self.result_dir = result_dir
        os.makedirs(self.result_dir, exist_ok=True)

    def collect_metric(self, case_id, service, namespace='default', metric='istio_requests_total', subset=None):
        """
        查询目标服务/版本的 Prometheus 指标，并保存到 results/prometheus 目录。
        :param case_id: 用例编号
        :param service: 目标服务名（如 reviews）
        :param namespace: 命名空间
        :param metric: 指标名
        :param subset: 目标版本（如 v2），可为 None
        :return: 查询结果
        """
        if subset:
            svc = f"{service}.{namespace}.svc.cluster.local"
            query = f'{metric}{{destination_service="{svc}", destination_version="{subset}"}}'
            file_prefix = f"{case_id}_{service}_v{subset}"
        else:
            svc = f"{service}.{namespace}.svc.cluster.local"
            query = f'{metric}{{destination_service="{svc}"}}'
            file_prefix = f"{case_id}_{service}"
        result = self.client.query(query)
        # 保存到文件
        with open(os.path.join(self.result_dir, f"{file_prefix}.json"), 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
