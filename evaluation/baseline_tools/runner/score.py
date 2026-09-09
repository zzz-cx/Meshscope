#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stratified scoring for baseline experiment."""
from __future__ import print_function

from collections import defaultdict


def _relkey(path, samples_root):
    path = path.replace("\\", "/")
    root = samples_root.replace("\\", "/").rstrip("/") + "/"
    if path.startswith(root):
        return path[len(root):]
    # fallback last two components
    parts = path.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1]


def score_method(per_sample_results, ground_truth, samples_root, confidence_threshold=0.7):
    """
    per_sample_results: list of adapter results (one per sample)
    Returns overall + stratified metrics and per-sample rows.
    """
    gt_samples = ground_truth.get("samples") or {}
    layers = ["static_only", "dynamic_only", "both", "none"]

    def empty_cm():
        return {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

    overall = empty_cm()
    by_layer = {k: empty_cm() for k in layers}
    rows = []

    for res in per_sample_results:
        cfg = res.get("config_file", "")
        key = _relkey(cfg, samples_root)
        gt = gt_samples.get(key)
        if gt is None:
            # try basename folder/file
            for k in gt_samples:
                if cfg.endswith(k) or key.endswith(k):
                    gt = gt_samples[k]
                    key = k
                    break
        if gt is None:
            rows.append({"sample": key, "status": "missing_gt"})
            continue

        has_fault = bool(gt.get("has_fault"))
        gt_type = gt.get("fault_type") or ""
        detectability = gt.get("detectability")
        if not detectability:
            ed = gt.get("expected_detection") or {}
            s, d = ed.get("static_detection"), ed.get("dynamic_detection")
            if has_fault is False:
                detectability = "none"
            elif s and d:
                detectability = "both"
            elif s and not d:
                detectability = "static_only"
            elif d and not s:
                detectability = "dynamic_only"
            else:
                detectability = "both"

        detected = []
        for f in res.get("detected_faults") or []:
            if float(f.get("confidence") or 0) >= confidence_threshold:
                detected.append(f.get("fault_type"))

        has_det = len(detected) > 0
        type_hit = gt_type in detected if has_fault else False

        bucket = overall
        layer_cm = by_layer.get(detectability, overall)

        if has_fault and has_det and type_hit:
            label = "TP"
            bucket["tp"] += 1
            layer_cm["tp"] += 1
        elif has_fault and has_det and not type_hit:
            label = "FP_type"
            bucket["fp"] += 1
            layer_cm["fp"] += 1
        elif has_fault and not has_det:
            label = "FN"
            bucket["fn"] += 1
            layer_cm["fn"] += 1
        elif (not has_fault) and has_det:
            label = "FP"
            bucket["fp"] += 1
            layer_cm["fp"] += 1
        else:
            label = "TN"
            bucket["tn"] += 1
            layer_cm["tn"] += 1

        rows.append({
            "sample": key,
            "detectability": detectability,
            "gt_fault": gt_type if has_fault else "correct",
            "detected": detected,
            "label": label,
            "t_detect_sec": res.get("t_detect_sec"),
            "available": res.get("available", True),
            "error": res.get("error"),
        })

    def metrics(cm):
        tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
        prec = tp / float(tp + fp) if (tp + fp) else 0.0
        rec = tp / float(tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        acc = (tp + tn) / float(tp + fp + fn + tn) if (tp + fp + fn + tn) else 0.0
        return {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "accuracy": round(acc, 4),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        }

    stratified = {}
    for layer, cm in by_layer.items():
        if cm["tp"] + cm["fp"] + cm["fn"] + cm["tn"] > 0:
            stratified[layer] = metrics(cm)

    times = [r.get("t_detect_sec") or 0 for r in per_sample_results if r.get("t_detect_sec") is not None]
    t_avg = sum(times) / float(len(times) or 1)

    return {
        "overall": metrics(overall),
        "stratified_recall": {
            layer: stratified[layer]["recall"] for layer in stratified
        },
        "stratified": stratified,
        "t_detect_avg_sec": round(t_avg, 4),
        "t_detect_sum_sec": round(sum(times), 4),
        "n_samples": len(rows),
        "rows": rows,
    }
