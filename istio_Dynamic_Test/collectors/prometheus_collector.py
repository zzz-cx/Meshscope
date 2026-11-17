"""PrometheusCollector —— 采集 Prometheus 指标。"""

import json
import os
from typing import Optional

from istio_Dynamic_Test.models.test_case import CollectionResult, TestCase
from istio_Dynamic_Test.utils.prometheus_utils import PrometheusClient
from .base import BaseCollector


class PrometheusCollector(BaseCollector):
    """Prometheus 指标采集器。"""

    def __init__(self, prometheus_url: str, namespace: str = "default",
                 result_dir: str = "results/prometheus"):
        self._namespace = namespace
        self._client = PrometheusClient(prometheus_url)
        self._result_dir = result_dir
        os.makedirs(result_dir, exist_ok=True)

    def collect(self, test_case: TestCase) -> CollectionResult:
        svc = test_case.host or test_case.source_service
        metrics = {}
        if test_case.expected_distribution:
            for ver in test_case.expected_distribution:
                result = self._query(test_case.case_id, svc, subset=ver)
                metrics[f"{svc}_{ver}"] = result
        else:
            result = self._query(test_case.case_id, svc, subset=test_case.expected_destination)
            metrics[svc] = result
        return CollectionResult(case_id=test_case.case_id, prometheus_metrics=metrics)

    def _query(self, case_id, service, metric='istio_requests_total', subset=None):
        svc_fqdn = f"{service}.{self._namespace}.svc.cluster.local"
        if subset:
            query = f'{metric}{{destination_service="{svc_fqdn}", destination_version="{subset}"}}'
            prefix = f"{case_id}_{service}_v{subset}"
        else:
            query = f'{metric}{{destination_service="{svc_fqdn}"}}'
            prefix = f"{case_id}_{service}"
        result = self._client.query(query)
        with open(os.path.join(self._result_dir, f"{prefix}.json"), 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
