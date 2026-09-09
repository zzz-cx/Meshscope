# Related Work（论文可贴稿）+ BibTeX

用途：将下方 **§Related Work** 正文直接贴入论文；**§Bibliography entries** 拷入 `.bib`；**§Table IV (revised)** 可选替换原表。  
维度含义与正文一致：*Cross-layer* = 控制面意图 ↔ 数据面/运行时行为对齐；*Runtime Enf.* = 运行时持续校验或策略闭环（非仅 CI/admission）。

---

## Related Work

### Configuration Validation for Cloud-Native Systems

Misconfigurations are a leading cause of cloud outages, and a large body of work targets Kubernetes manifests and infrastructure-as-code (IaC). Commercial and open-source static checkers such as KubeLinter and Checkov~\cite{kubelinter,checkov} scan YAML for schema violations and security best practices. Policy engines including OPA Gatekeeper and Kyverno~\cite{gatekeeper,kyverno} further enforce organizational constraints at admission time. Recent software-engineering studies quantify how well such tools cover community-prescribed security settings: ICSE'25 reports that even strong SAST tools achieve only moderate precision/recall on CIS-style Kubernetes hardening rules~\cite{rahman2025prescription}, while an FSE'25 industry experience report evaluates DAST-style scanners (e.g., Kubescape, Trivy, kube-bench) against live cluster deployments~\cite{rahman2025dast}. LLM-assisted detectors such as GenKubeSec~\cite{genkubesec2024} improve coverage of generic Kubernetes configuration faults, but remain confined to static manifests. Complementary systems research detects ``specious'' yet syntactically valid configurations that degrade performance via symbolic reasoning~\cite{hu2020violet}, or tests Kubernetes operators' state reconciliation end-to-end~\cite{gu2023acto,sun2022sieve}. These lines of work are effective for cluster security posture and controller correctness, yet they do not model service-mesh traffic intents (routing, splitting, retries, circuit breaking, rate limits) or verify that Envoy data-plane behavior matches declared policies.

\subsection Static Analysis for Service Meshes

For Istio specifically, the primary production diagnostic is \texttt{istioctl analyze}~\cite{istioctl-analyze}, which performs read-only static analysis over local files and/or live cluster objects and reports schema errors, missing references, unreachable routes, and related issues. Background analysis in the control plane (\texttt{istiod.enableAnalysis}) reuses the same analyzers~\cite{istioctl-analyze}. Industrial extensions such as Tetrate Config Analyzer~\cite{tetrate-tca} similarly lint Istio resources against best-practice rule sets. Prior academic static checkers for mesh or microservice configurations~\cite{ma-static-mesh} likewise operate on declarative objects without executing traffic. As summarized in Table~\ref{tab:related-validation}, these approaches are valuable shift-left gates but lack cross-layer correlation with the data plane and do not enforce correctness under runtime workloads.

\subsection Dynamic Testing, Resilience, and Mesh Correctness

A second line of work exercises microservices and meshes at runtime. Automated performance and scalability testing uses operational profiles to compare deployment alternatives~\cite{avritzer2018microservices,yu-dynamic-ms}. Empirical studies of Istio traffic-management policies characterize how circuit breaking and retries affect throughput and latency, and propose adaptive controllers that continuously retune these mechanisms~\cite{sedghpour2022icpe,sedghpour2023ic2e}. Such systems partially or fully close a runtime loop, but their goal is performance/resilience optimization rather than detecting whether a given configuration is semantically wrong relative to an operator intent or ground-truth fault label.

Closest to our setting, MeshTest~\cite{zheng2025meshtest} (NSDI'25) is the first automatic end-to-end testing framework for service-mesh traffic management. It generates configurations via service-flow exploration and uses a formal oracle plus real requests to find implementation bugs in Istio and Linkerd. MeshTest validates whether the \emph{mesh system} correctly realizes a generated configuration; in contrast, \system{} validates whether \emph{user-authored} configurations are consistent across control-plane intent and data-plane behavior, and whether policy effects hold under targeted traffic---i.e., configuration fault detection and enforcement for operators, not control-plane bug finding. Other large-scale mesh systems focus on architecture and overhead rather than validation~\cite{song2024canalmesh,zhu2023sidecars,saokar2023servicerouter}.

### Hybrid Pipelines and Positioning of \system{}

Industry compliance pipelines often chain static IaC scanners, admission policies, and manual integration tests~\cite{compliance-pipelines}. These workflows are hybrid in process but typically remain single-layer in semantics: they neither systematically derive runtime cases from static models nor reconcile control-plane declarations with observed Envoy behavior. Table~\ref{tab:related-validation} contrasts representative tools and studies along type (static / dynamic / hybrid), cross-layer checking, and runtime enforcement. \system{} is a hybrid validator that (i)~statically models Istio resources and their interactions, (ii)~generates compact, intent-driven traffic cases (including orthogonal designs), and (iii)~checks runtime outcomes against both static expectations and policy semantics---providing the cross-layer and runtime-enforcement properties missing from prior configuration validators.

% Optional one-liner if space is tight in intro instead of RW:
% Unlike \texttt{istioctl analyze} and IaC linters~\cite{istioctl-analyze,kubelinter,checkov}, and unlike MeshTest's implementation testing~\cite{zheng2025meshtest}, \system{} jointly validates user mesh configurations across control and data planes with runtime enforcement.

---

## Table IV (revised LaTeX)

```latex
\begin{table}[t]
\centering
\caption{Comparison of representative configuration validation studies and tools.
\emph{Cross-layer}: control-plane intent aligned with data-plane/runtime behavior.
\emph{Runtime Enf.}: continuous or closed-loop checking under traffic (not only CI/admission).}
\label{tab:related-validation}}
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{lccc}
\toprule
\textbf{Work / Tool} & \textbf{Type} & \textbf{Cross-layer} & \textbf{Runtime Enf.} \\
\midrule
Ma et al.~\cite{ma-static-mesh} & Static & \xmark & \xmark \\
\texttt{istioctl analyze}~\cite{istioctl-analyze} & Static & \xmark & \xmark \\
Gatekeeper / Kyverno~\cite{gatekeeper,kyverno} & Static$^\dagger$ & \xmark & \xmark$^\dagger$ \\
KubeLinter / Checkov~\cite{kubelinter,checkov} & Static & \xmark & \xmark \\
Rahman et al.\ (SAST study)~\cite{rahman2025prescription} & Static & \xmark & \xmark \\
MeshTest~\cite{zheng2025meshtest} & Dynamic & Partial & Partial \\
Yu et al.~\cite{yu-dynamic-ms} & Dynamic & \xmark & Partial \\
Avritzer et al.~\cite{avritzer2018microservices} & Dynamic & \xmark & Partial \\
Sedghpour et al.~\cite{sedghpour2022icpe,sedghpour2023ic2e} & Dynamic & \xmark & \cmark \\
Acto / Sieve~\cite{gu2023acto,sun2022sieve} & Dynamic$^\ddagger$ & \xmark & Partial \\
Compliance pipelines~\cite{compliance-pipelines} & Hybrid & \xmark & \xmark \\
\textbf{\system{}} & \textbf{Hybrid} & \textbf{\cmark} & \textbf{\cmark} \\
\bottomrule
\end{tabular}
\begin{tablenotes}
\footnotesize
\item $^\dagger$Admission control can block objects at apply-time; it does not verify Envoy-enforced traffic semantics.
\item $^\ddagger$Tests operator/controller reconciliation rather than mesh traffic-policy correctness.
\item MeshTest checks whether the mesh \emph{implementation} realizes generated configs; \system{} checks whether \emph{user} configs are fault-free and cross-layer consistent.
\end{tablenotes}
\end{table}
```

若版面紧，可删 Rahman / Acto–Sieve 两行，仅保留 MeshTest 作为 2023–26 新增主对比。

---

## Bibliography entries（建议 BibTeX）

> **注意：** `ma-static-mesh`、`yu-dynamic-ms`、`compliance-pipelines` 请用你原稿 `[7]`/`[13]`/`[22]` 的真实条目替换占位符。其余条目可直接用。

```bibtex
% ========== Service mesh static / tools ==========
@misc{istioctl-analyze,
  author       = {{Istio Authors}},
  title        = {Diagnose Your Configuration with istioctl analyze},
  howpublished = {\url{https://istio.io/latest/docs/ops/diagnostic-tools/istioctl-analyze/}},
  year         = {2024},
  note         = {Accessed 2026}
}

@misc{gatekeeper,
  author       = {{Open Policy Agent}},
  title        = {{OPA} {Gatekeeper}: Policy Controller for {Kubernetes}},
  howpublished = {\url{https://open-policy-agent.github.io/gatekeeper/}},
  year         = {2024}
}

@misc{kyverno,
  author       = {{Kyverno Authors}},
  title        = {{Kyverno}: {Kubernetes} Native Policy Management},
  howpublished = {\url{https://kyverno.io/}},
  year         = {2024}
}

@misc{kubelinter,
  author       = {{StackRox}},
  title        = {{KubeLinter}: Static Analysis for {Kubernetes}},
  howpublished = {\url{https://github.com/stackrox/kube-linter}},
  year         = {2024}
}

@misc{checkov,
  author       = {{Bridgecrew} and {Prisma Cloud}},
  title        = {{Checkov}: Static Analysis for Infrastructure-as-Code},
  howpublished = {\url{https://www.checkov.io/}},
  year         = {2024}
}

@misc{tetrate-tca,
  author       = {{Tetrate}},
  title        = {{Tetrate Config Analyzer} ({TCA})},
  howpublished = {\url{https://docs.tetrate.io/istio-subscription/tools/tca/}},
  year         = {2024}
}

% PLACEHOLDER: replace with your original Ma et al. [7]
@inproceedings{ma-static-mesh,
  author    = {Ma, Anon. and Others},
  title     = {[REPLACE] Static Analysis / Checking for Service Mesh or Microservice Configurations},
  booktitle = {[REPLACE venue]},
  year      = {[REPLACE]}
}

% ========== Dynamic / resilience / performance ==========
% PLACEHOLDER: replace with your original Yu et al. [13]
@inproceedings{yu-dynamic-ms,
  author    = {Yu, Anon. and Others},
  title     = {[REPLACE] Dynamic Testing / Validation of Microservice Configurations},
  booktitle = {[REPLACE venue]},
  year      = {[REPLACE]}
}

@inproceedings{avritzer2018microservices,
  author    = {Avritzer, Alberto and Ferme, Vincenzo and Janes, Andrea and Russo, Barbara and Schulz, Henning and van Hoorn, Andr{\'e}},
  title     = {A Quantitative Approach for the Assessment of Microservice Architecture Deployment Alternatives by Automated Performance Testing},
  booktitle = {Software Architecture ({ECSA})},
  series    = {LNCS},
  volume    = {11048},
  pages     = {159--174},
  publisher = {Springer},
  year      = {2018}
}

@inproceedings{sedghpour2022icpe,
  author    = {Saleh Sedghpour, Mohammad Reza and Klein, Cristian and Tordsson, Johan},
  title     = {An Empirical Study of Service Mesh Traffic Management Policies for Microservices},
  booktitle = {Proceedings of the 2022 {ACM}/{SPEC} International Conference on Performance Engineering ({ICPE})},
  pages     = {17--27},
  year      = {2022},
  doi       = {10.1145/3489525.3511686}
}

@inproceedings{sedghpour2023ic2e,
  author    = {Saleh Sedghpour, Mohammad Reza and Garlan, David and Schmerl, Bradley and Klein, Cristian and Tordsson, Johan},
  title     = {Breaking the Vicious Circle: Self-Adaptive Microservice Circuit Breaking and Retry},
  booktitle = {2023 {IEEE} International Conference on Cloud Engineering ({IC2E})},
  pages     = {32--42},
  year      = {2023},
  doi       = {10.1109/IC2E59103.2023.00012}
}

% ========== Closest related: MeshTest ==========
@inproceedings{zheng2025meshtest,
  author    = {Zheng, Naiqian and Qiao, Tianshuo and Liu, Xuanzhe and Jin, Xin},
  title     = {{MeshTest}: End-to-End Testing for Service Mesh Traffic Management},
  booktitle = {22nd {USENIX} Symposium on Networked Systems Design and Implementation ({NSDI} 25)},
  pages     = {301--316},
  year      = {2025},
  address   = {Philadelphia, PA},
  publisher = {{USENIX} Association},
  url       = {https://www.usenix.org/conference/nsdi25/presentation/zheng-naiqian}
}

% Extended journal version (cite if camera-ready prefers TOCS/journal):
@article{zheng2025meshtest-tocs,
  author  = {Zheng, Naiqian and Qiao, Tianshuo and Liu, Xuanzhe and Jin, Xin},
  title   = {Finding Service Mesh Bugs with Service Flow-Aware End-to-End Testing},
  journal = {ACM Transactions on Computer Systems},
  year    = {2025},
  note    = {doi:10.1145/3814612; cite NSDI version unless journal is preferred}
}

% ========== K8s misconfig SE venues (2024--2025) ==========
@inproceedings{rahman2025prescription,
  author    = {Rahman, Akond and others},
  title     = {On Prescription or Off Prescription? An Empirical Study of Community-Prescribed Security Configurations for {Kubernetes}},
  booktitle = {Proceedings of the 47th International Conference on Software Engineering ({ICSE})},
  year      = {2025},
  note      = {Research track; verify final author list from ACM/IEEE proceedings}
}

@inproceedings{rahman2025dast,
  author    = {Rahman, Akond and others},
  title     = {Dynamic Application Security Testing for {Kubernetes} Deployment: An Experience Report from Industry},
  booktitle = {Proceedings of the 33rd {ACM} International Conference on the Foundations of Soft\-ware Engineering ({FSE}) Industry},
  year      = {2025},
  note      = {Verify final venue track and author list; preprint: https://akondrahman.github.io/files/papers/fse25.pdf}
}

@inproceedings{genkubesec2024,
  author    = {Lavi, Aviv and others},
  title     = {{GenKubeSec}: {LLM}-Based {Kubernetes} Misconfiguration Detection, Localization, Reasoning, and Remediation},
  year      = {2024},
  note      = {arXiv:2405.19954; replace with published venue when available}
}

% ========== Orthogonal systems: operators / controllers / config ==========
@inproceedings{gu2023acto,
  author    = {Gu, Jiawei Tyler and Sun, Xudong and Zhang, Wentao and Jiang, Yuxuan and Wang, Chen and Vaziri, Mandana and Legunsen, Owolabi and Xu, Tianyin},
  title     = {{Acto}: Automatic End-to-End Testing for Operation Correctness of Cloud System Management},
  booktitle = {Proceedings of the 29th Symposium on Operating Systems Principles ({SOSP})},
  pages     = {288--305},
  year      = {2023},
  doi       = {10.1145/3600006.3613161}
}

@inproceedings{sun2022sieve,
  author    = {Sun, Xudong and Luo, Wenqing and Gu, Jiawei Tyler and Ganesan, Aishwarya and Alagappan, Ramnatthan and Gasch, Michael and Suresh, Lalith and Xu, Tianyin},
  title     = {Automatic Reliability Testing for Cluster Management Controllers},
  booktitle = {16th {USENIX} Symposium on Operating Systems Design and Implementation ({OSDI} 22)},
  pages     = {541--558},
  year      = {2022},
  publisher = {{USENIX} Association}
}

@inproceedings{hu2020violet,
  author    = {Hu, Yigong and Huang, Gongqi and Huang, Peng},
  title     = {Automated Reasoning and Detection of Specious Configuration in Large Systems with Symbolic Execution},
  booktitle = {14th {USENIX} Symposium on Operating Systems Design and Implementation ({OSDI} 20)},
  pages     = {719--734},
  year      = {2020},
  publisher = {{USENIX} Association}
}

% ========== Mesh systems (architecture / overhead; brief cite) ==========
@inproceedings{song2024canalmesh,
  author    = {Song, Ennan and others},
  title     = {Canal Mesh: A Cloud-Scale Sidecar-Free Multi-Tenant Service Mesh Architecture},
  booktitle = {Proceedings of the {ACM} {SIGCOMM} 2024 Conference},
  year      = {2024},
  note      = {Verify full author list from SIGCOMM'24 proceedings}
}

@inproceedings{zhu2023sidecars,
  author    = {Zhu, Xiangfeng and She, Guozhen and Xue, Bowen and Zhang, Yi and Zhang, Yongzhou and Zou, Xuan Kelvin and Duan, Xiongchun and He, Peng and Krishnamurthy, Arvind and Lentz, Matthew and others},
  title     = {Dissecting Overheads of Service Mesh Sidecars},
  booktitle = {Proceedings of the 2023 {ACM} Symposium on Cloud Computing ({SoCC})},
  year      = {2023}
}

@inproceedings{saokar2023servicerouter,
  author    = {Saokar, Harshit and Demetriou, Soteris and Magerko, Nick and Kontorovich, Max and Kirstein, Justin and Leibold, Margot and Skarlatos, Dimitrios and Khandelwal, Hitesh and Tang, Chunqiang},
  title     = {{ServiceRouter}: Hyperscale and Minimal Cost Service Mesh at {Meta}},
  booktitle = {17th {USENIX} Symposium on Operating Systems Design and Implementation ({OSDI} 23)},
  year      = {2023},
  publisher = {{USENIX} Association}
}

% PLACEHOLDER: replace with your original compliance-pipelines [22]
@misc{compliance-pipelines,
  author       = {{REPLACE}},
  title        = {[REPLACE] Compliance / GitOps Configuration Validation Pipelines},
  year         = {[REPLACE]},
  howpublished = {[REPLACE]}
}
```

---

## 使用说明（勿贴进论文）

1. 全文中的 `\system{}` 换成你的宏（如 `\textsc{ConfigPilot}` / `CONFIGPILOT`）。  
2. 用原稿真实 bib **替换三处 PLACEHOLDER**：`ma-static-mesh`、`yu-dynamic-ms`、`compliance-pipelines`。  
3. `rahman2025*` / `genkubesec2024` / `song2024canalmesh` 在 camera-ready 前用正式 proceedings 作者列表校准（当前已可用，但 ICSE/FSE 最终页码以 ACM DL 为准）。  
4. 与 MeshTest 的区分句已写进 RW 与表注；审稿人若质疑 “为何不直接比 MeshTest 准确率”，答：任务不同（实现 bug vs 用户配置故障），语料与 oracle 不可直接复用。  
5. 若页数紧：RW 可只保留四段中的后三段，并把第一段压成 4–5 句。
