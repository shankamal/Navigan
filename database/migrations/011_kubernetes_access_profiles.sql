INSERT INTO access_management.kubernetes_access_profiles(
 profile_id,profile_code,profile_name,description,scope_type,permissions,created_by
) VALUES
(
 'KAP-NAMESPACE-VIEWER','NAMESPACE_VIEWER','Namespace Viewer',
 'Read workloads, services, configuration metadata, events and logs in one namespace.',
 'NAMESPACE',
 '[
   {"apiGroups":[""],"resources":["pods","pods/log","services","configmaps","events"],"verbs":["get","list","watch"]},
   {"apiGroups":["apps"],"resources":["deployments","statefulsets","daemonsets","replicasets"],"verbs":["get","list","watch"]}
 ]'::jsonb,
 'SYSTEM'
),
(
 'KAP-NAMESPACE-OPERATOR','NAMESPACE_OPERATOR','Namespace Operator',
 'Operate approved workloads in one namespace without managing RBAC or secrets.',
 'NAMESPACE',
 '[
   {"apiGroups":[""],"resources":["pods","pods/log","services","configmaps","events"],"verbs":["get","list","watch"]},
   {"apiGroups":["apps"],"resources":["deployments","statefulsets","daemonsets","replicasets"],"verbs":["get","list","watch","patch","update"]}
 ]'::jsonb,
 'SYSTEM'
),
(
 'KAP-CLUSTER-OPERATOR','CLUSTER_OPERATOR','Cluster Operator',
 'View cluster-wide health and operate workloads without changing Kubernetes RBAC.',
 'CLUSTER',
 '[
   {"apiGroups":[""],"resources":["nodes","namespaces","pods","pods/log","services","configmaps","events"],"verbs":["get","list","watch"]},
   {"apiGroups":["apps"],"resources":["deployments","statefulsets","daemonsets","replicasets"],"verbs":["get","list","watch","patch","update"]}
 ]'::jsonb,
 'SYSTEM'
)
ON CONFLICT(profile_code) DO NOTHING;
