# F1--F10 Baseline Suite Results

Generated: 2026-07-29T16:56:22.692859

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
| istioctl | 1.000 | 0.200 | 0.333 | 0.0344 |
| Naive Dyn. | 1.000 | 0.100 | 0.182 | 0.0040 |
| Dyn. Only | 1.000 | 0.700 | 0.824 | 0.0039 |
| Hybrid | 1.000 | 1.000 | 1.000 | 0.0065 |

