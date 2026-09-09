# F1--F10 Baseline Suite Results (CLUSTER)

Generated: 2026-07-29T17:23:09.852329
Namespace: `baseline-bookinfo`
Ingress: `http://192.168.1.69:31605`

| ID | Type | istioctl | Naive Dyn. | Dyn. Only | Hybrid |
|----|------|----------|------------|-----------|--------|
| F1 | Missing subset definition | Y | N | N | Y |
| F2 | Authorization conflict | Y | N | N | Y |
| F3 | Inconsistent mTLS mode | N | N | Y | Y |
| F4 | Timeout mismatch | N | N | Y | Y |
| F5 | Traffic split drift | N | N | Y | Y |
| F6 | Retry omission in runtime | N | N | Y | Y |
| F7 | Circuit breaker ineffective | N | N | Y | Y |
| F8 | Partial timeout propagation | N | N | Y | Y |
| F9 | Incorrect routing dependency | N | N | N | Y |
| F10 | Runtime policy enforcement gap | N | Y | Y | Y |

## Overall metrics

| Method | Prec | Rec | F1 | T_avg (s) |
|--------|------|-----|----|-----------|
| istioctl | 1.000 | 0.200 | 0.333 | 0.0332 |
| Naive Dyn. | 0.250 | 0.143 | 0.182 | 4.9507 |
| Dyn. Only | 0.875 | 0.778 | 0.824 | 6.0459 |
| Hybrid | 1.000 | 1.000 | 1.000 | 5.9970 |

