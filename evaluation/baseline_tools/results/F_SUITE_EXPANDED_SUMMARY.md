# F1--F10 Expanded Baseline Comparison

Generated: 2026-07-29T18:21:43.593668

| ID | Type | istioctl | Static Only | PolicyLite | LintBP | SchemaCRD | kubectl-dry(client) | kubectl-dry(server) | kube-linter | kubeconform | Kyverno | Checkov | Dyn. Only | Hybrid |
|----|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| F1 | Missing subset definition | Y | Y | N | N | N | N | N | N | N | N | — | N | Y |
| F2 | Authorization conflict | Y | Y | Y | N | N | N | N | N | N | N | — | N | Y |
| F3 | Inconsistent mTLS mode | N | Y | Y | N | N | N | N | N | N | Y | — | Y | Y |
| F4 | Timeout mismatch | N | Y | N | N | N | N | N | N | N | N | — | Y | Y |
| F5 | Traffic split drift | N | Y | N | N | N | N | N | N | N | N | — | Y | Y |
| F6 | Retry omission in runtime | N | N | N | N | N | N | N | N | N | N | — | Y | Y |
| F7 | Circuit breaker ineffective | N | Y | N | N | N | N | N | N | N | N | — | Y | Y |
| F8 | Partial timeout propagation | N | N | N | N | N | N | N | N | N | N | — | Y | Y |
| F9 | Incorrect routing dependency | N | Y | N | N | N | N | N | N | N | N | — | N | Y |
| F10 | Runtime policy enforcement gap | N | N | N | N | N | N | N | N | N | N | — | Y | Y |

## Overall metrics

| Method | Available | Prec | Rec | F1 | T_avg (s) |
|--------|-----------|------|-----|----|-----------|
| istioctl | yes | 1.000 | 0.200 | 0.333 | 0.0396 |
| Static Only | yes | 0.778 | 0.875 | 0.824 | 0.0027 |
| PolicyLite | yes | 1.000 | 0.200 | 0.333 | 0.0025 |
| LintBP | yes | 0.000 | 0.000 | 0.000 | 0.0025 |
| SchemaCRD | yes | 0.000 | 0.000 | 0.000 | 0.0026 |
| kubectl-dry(client) | yes | 0.000 | 0.000 | 0.000 | 0.1210 |
| kubectl-dry(server) | yes | 0.000 | 0.000 | 0.000 | 0.1258 |
| kube-linter | yes | 0.000 | 0.000 | 0.000 | 0.0303 |
| kubeconform | yes | 0.000 | 0.000 | 0.000 | 1.2654 |
| Kyverno | yes | 1.000 | 0.100 | 0.182 | 0.3024 |
| Checkov | NO | 0.000 | 0.000 | 0.000 | 0.0267 |
| Dyn. Only | yes | 1.000 | 0.700 | 0.824 | 0.0043 |
| Hybrid | yes | 1.000 | 1.000 | 1.000 | 0.0065 |

## Notes

- `—` = tool unavailable on this host.
- PolicyLite / LintBP / SchemaCRD are lightweight stand-ins when Gatekeeper/kube-linter schemas are limited.
- Dyn. Only / Hybrid use yaml_oracle in this expanded offline sweep (cluster live run is separate).
- Type-matched scoring: wrong fault_type counts as miss/FP_type, not TP.

