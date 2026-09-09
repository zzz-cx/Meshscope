# Baseline Tools Results

Generated: 2026-07-29T16:56:23.703102

## Table A — Overall

| Method | Prec | Rec | F1 | TP/FP/FN/TN | T_detect_avg (s) | Available |
|--------|------|-----|----|-------------|------------------|-----------|
| S-Istio-offline | 0.500 | 0.059 | 0.105 | 1/1/16/1 | 0.0330 | yes |
| D-Naive | 1.000 | 0.056 | 0.105 | 1/0/17/1 | 0.0045 | yes |
| D-Ours | 0.917 | 0.647 | 0.759 | 11/1/6/1 | 0.0044 | yes |
| H-Ours | 0.944 | 1.000 | 0.971 | 17/1/0/1 | 0.0076 | yes |

## Table B — Stratified Recall

| Method | L-Static (static_only) | L-Dynamic (dynamic_only) | L-Both | L-Neg (none) |
|--------|------------------------|--------------------------|--------|--------------|
| S-Istio-offline | 0.000 | 0.000 | 0.125 | 0.000 |
| D-Naive | 0.000 | 0.143 | 0.000 | 0.000 |
| D-Ours | 0.000 | 1.000 | 0.500 | 0.000 |
| H-Ours | 1.000 | 1.000 | 1.000 | 0.000 |

## Notes

- Primary static baseline: **S-Istio-offline** (`istioctl analyze --use-kube=false`).
- S-Istio-cluster reported when kube context is available.
- D-Naive / D-Ours / H-Ours without `--cluster` use **yaml_oracle** (policy-content runtime signals); with `--cluster` they also apply+curl.
- S-Ours / H-Ours are ablations of MeshScope, not external competitors.
- S-Lint / S-Schema skipped gracefully if binaries missing.

