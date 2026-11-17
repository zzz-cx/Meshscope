"""Machine-readable support ledger; unknown does not mean verified."""


def capabilities():
    return {'schema': 'configpilot.capabilities/1', 'default_engine': 'relational',
        'features': [
            {'id': 'relational_model', 'status': 'supported', 'scope': 'typed identities, ordered HTTP rules, attachment, references; opaque fields retained'},
            {'id': 'obligation_planning', 'status': 'supported', 'scope': 'complete obligation set, conservative whole-context reuse, unknown retained'},
            {'id': 'request_evidence', 'status': 'supported', 'scope': 'correlated /2 fixture receipts; generic HTTP, split, retry budget and small-pool contracts'},
            {'id': 'collection_sharing', 'status': 'supported', 'scope': 'batched shared controlled receipt collector; not arbitrary Prometheus queries'},
            {'id': 'conflict_scheduling', 'status': 'supported', 'scope': 'shared reads, exclusive pool state, total request budget, waiting yields worker'},
            {'id': 'computation', 'status': 'supported', 'scope': 'indexed closure, serial/thread/process and optional explicitly built Go binary'},
            {'id': 'bounded_backend', 'status': 'supported', 'scope': 'record cap, completed-record retention and release after persistence'},
            {'id': 'dependency_diagnosis', 'status': 'supported', 'scope': 'policy/config/evidence graph, dependency-distance candidates; not proven causality'},
            {'id': 'field_inheritance', 'status': 'partial', 'scope': 'relationship retained; runtime activation not licensed for unresolved inheritance'},
            {'id': 'cross_layer_equivalence', 'status': 'partial', 'scope': 'bidirectional finite witnesses on projected models; raw Envoy relational projection and full equivalence incomplete'},
            {'id': 'native_telemetry', 'status': 'partial', 'scope': 'legacy collectors exist; generic request-level Envoy/Prometheus/OTel adaptation incomplete'},
            {'id': 'outlier_ejection', 'status': 'unsupported', 'scope': 'requires distinct actual endpoints and isolated ejection/recovery evidence'},
            {'id': 'security_grpc_dynamic', 'status': 'partial', 'scope': 'legacy gRPC transport exists; new identity-aware mTLS/auth and gRPC oracles not implemented'},
            {'id': 'automatic_capacity_discovery', 'status': 'unsupported', 'scope': 'explicit bounded budget only; no capacity inference'},
            {'id': 'arbitrary_policy_merging', 'status': 'unsupported', 'scope': 'no universal non-interference or fault-detection guarantee'},
        ]}
