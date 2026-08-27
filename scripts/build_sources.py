"""Gera/atualiza sources.yaml com URLs verificadas.

Estratégia:
  1. Catálogo declarativo (mvp + full) com URLs candidatas.
  2. Cada URL é resolvida via HTTP (segue redirects). Guardamos a URL final
     canônica quando 200; URLs não-200 são reportadas como FALHA.
  3. --write só grava se não houver falhas (ou use --force).

Uso:
    python scripts/build_sources.py            # dry-run: valida e reporta
    python scripts/build_sources.py --write     # valida e grava se tudo ok
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import urllib.request
import urllib.error
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src/cip/ingestion/sources.yaml"
UA = "Mozilla/5.0 (compatible; CIP-LinkAudit/1.0)"

# ─────────────────────────── CATÁLOGO ───────────────────────────
# Estrutura: scope -> cloud -> lista de dicts (service, category, doc_type,
# framework?, source, urls[])

CATALOG = {
    "mvp": {
        "aws": [
            dict(source="aws-well-architected", framework="well-architected",
                 service="well-architected", category="governance", doc_type="whitepaper",
                 urls=[
                     "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
                     "https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html",
                     "https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html",
                     "https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html",
                     "https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html",
                     "https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html",
                     "https://docs.aws.amazon.com/wellarchitected/latest/sustainability-pillar/sustainability-pillar.html",
                 ]),
        ],
        "gcp": [
            dict(source="gcp-architecture-framework", framework="architecture-framework",
                 service="architecture-framework", category="governance", doc_type="whitepaper",
                 urls=[
                     "https://docs.cloud.google.com/architecture/framework",
                     "https://docs.cloud.google.com/architecture/framework/security",
                     "https://docs.cloud.google.com/architecture/framework/reliability",
                     "https://docs.cloud.google.com/architecture/framework/cost-optimization",
                     "https://docs.cloud.google.com/architecture/framework/operational-excellence",
                     "https://docs.cloud.google.com/architecture/framework/performance-optimization",
                 ]),
        ],
        "azure": [
            dict(source="azure-well-architected", framework="well-architected",
                 service="well-architected", category="governance", doc_type="whitepaper",
                 urls=[
                     "https://learn.microsoft.com/en-us/azure/well-architected/",
                     "https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/",
                     "https://learn.microsoft.com/en-us/azure/well-architected/security/",
                     "https://learn.microsoft.com/en-us/azure/well-architected/reliability/",
                     "https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence/",
                     "https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency/",
                     "https://learn.microsoft.com/en-us/azure/well-architected/sustainability/",
                 ]),
        ],
    },
    "full": {"aws": [], "gcp": [], "azure": []},
}


def svc(cloud, source, service, category, urls, doc_type="reference"):
    CATALOG["full"][cloud].append(
        dict(source=source, service=service, category=category, doc_type=doc_type, urls=urls)
    )


# ─────────────────────────── AWS ───────────────────────────
A = "https://docs.aws.amazon.com"
svc("aws", "aws-docs", "ec2", "compute", [
    f"{A}/AWSEC2/latest/UserGuide/concepts.html",
    f"{A}/AWSEC2/latest/UserGuide/instance-types.html",
    f"{A}/AWSEC2/latest/UserGuide/ec2-best-practices.html",
])
svc("aws", "aws-docs", "lambda", "compute", [
    f"{A}/lambda/latest/dg/welcome.html",
    f"{A}/lambda/latest/dg/lambda-invocation.html",
    f"{A}/lambda/latest/dg/best-practices.html",
    f"{A}/lambda/latest/dg/lambda-concurrency.html",
])
svc("aws", "aws-docs", "ecs", "compute", [
    f"{A}/AmazonECS/latest/developerguide/Welcome.html",
    f"{A}/AmazonECS/latest/developerguide/AWS_Fargate.html",
    f"{A}/AmazonECS/latest/bestpracticesguide/intro.html",
])
svc("aws", "aws-docs", "eks", "compute", [
    f"{A}/eks/latest/userguide/what-is-eks.html",
    f"{A}/eks/latest/userguide/eks-architecture.html",
    f"{A}/eks/latest/userguide/managed-node-groups.html",
    f"{A}/eks/latest/best-practices/introduction.html",
])
svc("aws", "aws-docs", "autoscaling", "compute", [
    f"{A}/autoscaling/ec2/userguide/what-is-amazon-ec2-auto-scaling.html",
    f"{A}/autoscaling/ec2/userguide/ec2-auto-scaling-termination-policies.html",
])
svc("aws", "aws-docs", "batch", "compute", [
    f"{A}/batch/latest/userguide/what-is-batch.html",
    f"{A}/batch/latest/userguide/best-practices.html",
])
# Storage
svc("aws", "aws-docs", "s3", "storage", [
    f"{A}/AmazonS3/latest/userguide/Welcome.html",
    f"{A}/AmazonS3/latest/userguide/storage-class-intro.html",
    f"{A}/AmazonS3/latest/userguide/object-lifecycle-mgmt.html",
    f"{A}/AmazonS3/latest/userguide/optimizing-performance.html",
])
svc("aws", "aws-docs", "ebs", "storage", [
    f"{A}/ebs/latest/userguide/what-is-ebs.html",
    f"{A}/ebs/latest/userguide/ebs-volume-types.html",
])
svc("aws", "aws-docs", "efs", "storage", [
    f"{A}/efs/latest/ug/whatisefs.html",
    f"{A}/efs/latest/ug/performance.html",
])
svc("aws", "aws-docs", "fsx", "storage", [
    f"{A}/fsx/latest/WindowsGuide/what-is.html",
])
# Database
svc("aws", "aws-docs", "rds", "database", [
    f"{A}/AmazonRDS/latest/UserGuide/Welcome.html",
    f"{A}/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html",
    f"{A}/AmazonRDS/latest/UserGuide/CHAP_BestPractices.html",
])
svc("aws", "aws-docs", "aurora", "database", [
    f"{A}/AmazonRDS/latest/AuroraUserGuide/CHAP_AuroraOverview.html",
    f"{A}/AmazonRDS/latest/AuroraUserGuide/Aurora.Replication.html",
    f"{A}/AmazonRDS/latest/AuroraUserGuide/BestPractices.html",
])
svc("aws", "aws-docs", "dynamodb", "database", [
    f"{A}/amazondynamodb/latest/developerguide/Introduction.html",
    f"{A}/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html",
    f"{A}/amazondynamodb/latest/developerguide/best-practices.html",
])
svc("aws", "aws-docs", "elasticache", "database", [
    f"{A}/AmazonElastiCache/latest/dg/WhatIs.html",
    f"{A}/AmazonElastiCache/latest/dg/BestPractices.html",
])
svc("aws", "aws-docs", "redshift", "database", [
    f"{A}/redshift/latest/mgmt/welcome.html",
    f"{A}/redshift/latest/dg/c_best-practices-best-practices.html",
])
svc("aws", "aws-docs", "documentdb", "database", [
    f"{A}/documentdb/latest/developerguide/what-is.html",
])
# Networking
svc("aws", "aws-docs", "vpc", "networking", [
    f"{A}/vpc/latest/userguide/what-is-amazon-vpc.html",
    f"{A}/vpc/latest/userguide/configure-subnets.html",
    f"{A}/vpc/latest/userguide/vpc-security-groups.html",
])
svc("aws", "aws-docs", "elb", "networking", [
    f"{A}/elasticloadbalancing/latest/application/introduction.html",
    f"{A}/elasticloadbalancing/latest/network/introduction.html",
])
svc("aws", "aws-docs", "cloudfront", "networking", [
    f"{A}/AmazonCloudFront/latest/DeveloperGuide/Introduction.html",
    f"{A}/AmazonCloudFront/latest/DeveloperGuide/ConfiguringCaching.html",
])
svc("aws", "aws-docs", "route53", "networking", [
    f"{A}/Route53/latest/DeveloperGuide/Welcome.html",
    f"{A}/Route53/latest/DeveloperGuide/routing-policy.html",
])
svc("aws", "aws-docs", "transit-gateway", "networking", [
    f"{A}/vpc/latest/tgw/what-is-transit-gateway.html",
])
# Security
svc("aws", "aws-docs", "iam", "security", [
    f"{A}/IAM/latest/UserGuide/introduction.html",
    f"{A}/IAM/latest/UserGuide/best-practices.html",
    f"{A}/IAM/latest/UserGuide/access_policies.html",
])
svc("aws", "aws-docs", "kms", "security", [
    f"{A}/kms/latest/developerguide/overview.html",
    f"{A}/kms/latest/developerguide/concepts.html",
])
svc("aws", "aws-docs", "secretsmanager", "security", [
    f"{A}/secretsmanager/latest/userguide/intro.html",
    f"{A}/secretsmanager/latest/userguide/best-practices.html",
])
svc("aws", "aws-docs", "guardduty", "security", [
    f"{A}/guardduty/latest/ug/what-is-guardduty.html",
    f"{A}/guardduty/latest/ug/guardduty_findings.html",
])
svc("aws", "aws-docs", "waf", "security", [
    f"{A}/waf/latest/developerguide/what-is-aws-waf.html",
    f"{A}/waf/latest/developerguide/best-practices.html",
])
svc("aws", "aws-docs", "config", "governance", [
    f"{A}/config/latest/developerguide/WhatIsConfig.html",
])
svc("aws", "aws-docs", "organizations", "governance", [
    f"{A}/organizations/latest/userguide/orgs_introduction.html",
    f"{A}/organizations/latest/userguide/orgs_best-practices.html",
])
# Observability
svc("aws", "aws-docs", "cloudwatch", "observability", [
    f"{A}/AmazonCloudWatch/latest/monitoring/WhatIsCloudWatch.html",
    f"{A}/AmazonCloudWatch/latest/monitoring/cloudwatch_concepts.html",
])
svc("aws", "aws-docs", "xray", "observability", [f"{A}/xray/latest/devguide/aws-xray.html"])
svc("aws", "aws-docs", "cloudtrail", "observability", [
    f"{A}/awscloudtrail/latest/userguide/cloudtrail-user-guide.html",
])
# DevOps
svc("aws", "aws-docs", "cloudformation", "devops", [
    f"{A}/AWSCloudFormation/latest/UserGuide/Welcome.html",
    f"{A}/AWSCloudFormation/latest/UserGuide/best-practices.html",
])
svc("aws", "aws-docs", "cdk", "devops", [
    f"{A}/cdk/v2/guide/home.html",
    f"{A}/cdk/v2/guide/best-practices.html",
])
# Integration
svc("aws", "aws-docs", "eventbridge", "integration", [
    f"{A}/eventbridge/latest/userguide/eb-what-is.html",
])
svc("aws", "aws-docs", "sqs", "integration", [
    f"{A}/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html",
    f"{A}/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-best-practices.html",
])
svc("aws", "aws-docs", "sns", "integration", [
    f"{A}/sns/latest/dg/welcome.html",
])
svc("aws", "aws-docs", "api-gateway", "integration", [
    f"{A}/apigateway/latest/developerguide/welcome.html",
    f"{A}/apigateway/latest/developerguide/api-gateway-basic-concept.html",
])
svc("aws", "aws-docs", "step-functions", "integration", [
    f"{A}/step-functions/latest/dg/welcome.html",
    f"{A}/step-functions/latest/dg/sfn-stepfunctions-standard-vs-express.html",
])
svc("aws", "aws-docs", "kinesis", "integration", [
    f"{A}/streams/latest/dev/introduction.html",
])
svc("aws", "aws-docs", "msk", "integration", [
    f"{A}/msk/latest/developerguide/what-is-msk.html",
])
# Analytics
svc("aws", "aws-docs", "glue", "analytics", [
    f"{A}/glue/latest/dg/what-is-glue.html",
])
svc("aws", "aws-docs", "athena", "analytics", [
    f"{A}/athena/latest/ug/what-is.html",
    f"{A}/athena/latest/ug/performance-tuning.html",
])
# AI/ML
svc("aws", "aws-docs", "bedrock", "ai-ml", [
    f"{A}/bedrock/latest/userguide/what-is-bedrock.html",
    f"{A}/bedrock/latest/userguide/model-access.html",
])
svc("aws", "aws-docs", "sagemaker", "ai-ml", [
    f"{A}/sagemaker/latest/dg/whatis.html",
])

# ─────────────────────────── GCP (docs.cloud.google.com) ───────────────────────────
G = "https://docs.cloud.google.com"
svc("gcp", "gcp-docs", "compute-engine", "compute", [
    f"{G}/compute/docs",
    f"{G}/compute/docs/instances",
    f"{G}/compute/docs/machine-resource",
])
svc("gcp", "gcp-docs", "cloud-run", "compute", [
    f"{G}/run/docs",
    f"{G}/run/docs/tips/general",
])
svc("gcp", "gcp-docs", "cloud-functions", "compute", [
    f"{G}/functions/docs",
    f"{G}/functions/docs/bestpractices/tips",
])
svc("gcp", "gcp-docs", "gke", "compute", [
    f"{G}/kubernetes-engine/docs/concepts/kubernetes-engine-overview",
    f"{G}/kubernetes-engine/docs/how-to/hardening-your-cluster",
    f"{G}/kubernetes-engine/docs/concepts/node-pools",
])
svc("gcp", "gcp-docs", "gke-autopilot", "compute", [
    f"{G}/kubernetes-engine/docs/concepts/autopilot-overview",
])
svc("gcp", "gcp-docs", "dataflow", "compute", [
    f"{G}/dataflow/docs",
    f"{G}/dataflow/docs/overview",
])
svc("gcp", "gcp-docs", "app-engine", "compute", [
    f"{G}/appengine/docs",
])
# Storage
svc("gcp", "gcp-docs", "cloud-storage", "storage", [
    f"{G}/storage/docs",
    f"{G}/storage/docs/storage-classes",
    f"{G}/storage/docs/lifecycle",
    f"{G}/storage/docs/best-practices",
])
svc("gcp", "gcp-docs", "persistent-disk", "storage", [
    f"{G}/compute/docs/disks",
    f"{G}/compute/docs/disks/performance",
])
svc("gcp", "gcp-docs", "filestore", "storage", [
    f"{G}/filestore/docs",
])
# Database
svc("gcp", "gcp-docs", "cloud-sql", "database", [
    f"{G}/sql/docs",
    f"{G}/sql/docs/postgres",
    f"{G}/sql/docs/mysql",
])
svc("gcp", "gcp-docs", "alloydb", "database", [
    f"{G}/alloydb/docs",
    f"{G}/alloydb/docs/overview",
])
svc("gcp", "gcp-docs", "spanner", "database", [
    f"{G}/spanner/docs",
    f"{G}/spanner/docs/instances",
])
svc("gcp", "gcp-docs", "firestore", "database", [
    f"{G}/firestore/native/docs",
    f"{G}/firestore/native/docs/data-model",
    f"{G}/firestore/native/docs/best-practices",
])
svc("gcp", "gcp-docs", "bigtable", "database", [
    f"{G}/bigtable/docs",
])
svc("gcp", "gcp-docs", "memorystore", "database", [
    f"{G}/memorystore/docs",
    f"{G}/memorystore/docs/redis",
])
svc("gcp", "gcp-docs", "bigquery", "analytics", [
    f"{G}/bigquery/docs/introduction",
    f"{G}/bigquery/docs/best-practices-performance-overview",
    f"{G}/bigquery/docs/storage_overview",
])
# Networking
svc("gcp", "gcp-docs", "vpc", "networking", [
    f"{G}/vpc/docs",
    f"{G}/vpc/docs/vpc",
    f"{G}/vpc/docs/firewalls",
])
svc("gcp", "gcp-docs", "cloud-load-balancing", "networking", [
    f"{G}/load-balancing/docs",
    f"{G}/load-balancing/docs/https",
])
svc("gcp", "gcp-docs", "cloud-cdn", "networking", [
    f"{G}/cdn/docs",
    f"{G}/cdn/docs/best-practices",
])
svc("gcp", "gcp-docs", "cloud-dns", "networking", [
    f"{G}/dns/docs",
    f"{G}/dns/docs/overview",
])
svc("gcp", "gcp-docs", "cloud-nat", "networking", [
    f"{G}/nat/docs/overview",
])
# Security
svc("gcp", "gcp-docs", "iam", "security", [
    f"{G}/iam/docs",
    f"{G}/iam/docs/roles-permissions",
])
svc("gcp", "gcp-docs", "cloud-kms", "security", [
    f"{G}/kms/docs",
])
svc("gcp", "gcp-docs", "secret-manager", "security", [
    f"{G}/secret-manager/docs",
    f"{G}/secret-manager/docs/best-practices",
])
svc("gcp", "gcp-docs", "security-command-center", "security", [
    f"{G}/security-command-center/docs",
    f"{G}/security-command-center/docs/security-command-center-overview",
])
svc("gcp", "gcp-docs", "cloud-armor", "security", [
    f"{G}/armor/docs",
])
# Observability
svc("gcp", "gcp-docs", "cloud-logging", "observability", [
    f"{G}/logging/docs",
])
svc("gcp", "gcp-docs", "cloud-monitoring", "observability", [
    f"{G}/monitoring/docs",
    f"{G}/monitoring/alerts",
])
svc("gcp", "gcp-docs", "cloud-trace", "observability", [
    f"{G}/trace/docs",
])
# DevOps
svc("gcp", "gcp-docs", "cloud-build", "devops", [
    f"{G}/build/docs",
])
svc("gcp", "gcp-docs", "cloud-deploy", "devops", [
    f"{G}/deploy/docs",
])
svc("gcp", "gcp-docs", "artifact-registry", "devops", [
    f"{G}/artifact-registry/docs",
])
svc("gcp", "gcp-docs", "cloud-composer", "devops", [
    f"{G}/composer/docs",
])
# Integration
svc("gcp", "gcp-docs", "pubsub", "integration", [
    f"{G}/pubsub/docs/overview",
    f"{G}/pubsub/docs/publisher",
    f"{G}/pubsub/docs/subscriber",
])
svc("gcp", "gcp-docs", "cloud-tasks", "integration", [
    f"{G}/tasks/docs",
])
svc("gcp", "gcp-docs", "cloud-scheduler", "integration", [
    f"{G}/scheduler/docs",
])
# AI/ML
svc("gcp", "gcp-docs", "vertex-ai", "ai-ml", [
    f"{G}/vertex-ai/docs",
    f"{G}/vertex-ai/docs/start/introduction-unified-platform",
])
svc("gcp", "gcp-docs", "gemini", "ai-ml", [
    f"{G}/vertex-ai/generative-ai/docs/models/gemini/2-5-flash",
])

# ─────────────────────────── AZURE ───────────────────────────
Z = "https://learn.microsoft.com/en-us/azure"
svc("azure", "azure-docs", "virtual-machines", "compute", [
    f"{Z}/virtual-machines/overview",
    f"{Z}/virtual-machines/sizes/overview",
])
svc("azure", "azure-docs", "app-service", "compute", [
    f"{Z}/app-service/overview",
    f"{Z}/app-service/overview-hosting-plans",
])
svc("azure", "azure-docs", "container-apps", "compute", [
    f"{Z}/container-apps/overview",
])
svc("azure", "azure-docs", "functions", "compute", [
    f"{Z}/azure-functions/functions-overview",
    f"{Z}/azure-functions/functions-best-practices",
])
svc("azure", "azure-docs", "aks", "compute", [
    f"{Z}/aks/what-is-aks",
    f"{Z}/aks/concepts-clusters-workloads",
    f"{Z}/aks/best-practices",
])
svc("azure", "azure-docs", "aks-hybrid", "compute", [
    f"{Z}/aks/hybrid/aks-hybrid-options-overview",
])
svc("azure", "azure-docs", "vm-scale-sets", "compute", [
    f"{Z}/virtual-machine-scale-sets/overview",
])
# Storage
svc("azure", "azure-docs", "blob-storage", "storage", [
    f"{Z}/storage/blobs/storage-blobs-overview",
    f"{Z}/storage/blobs/access-tiers-overview",
    f"{Z}/storage/blobs/lifecycle-management-overview",
])
svc("azure", "azure-docs", "disk-storage", "storage", [
    f"{Z}/virtual-machines/managed-disks-overview",
    f"{Z}/virtual-machines/disks-types",
])
svc("azure", "azure-docs", "azure-files", "storage", [
    f"{Z}/storage/files/storage-files-introduction",
    f"{Z}/storage/files/storage-files-planning",
])
svc("azure", "azure-docs", "netapp-files", "storage", [
    f"{Z}/azure-netapp-files/azure-netapp-files-introduction",
])
# Database
svc("azure", "azure-docs", "postgresql", "database", [
    f"{Z}/postgresql/flexible-server/overview",
    f"{Z}/postgresql/flexible-server/concepts-high-availability",
])
svc("azure", "azure-docs", "mysql", "database", [
    f"{Z}/mysql/flexible-server/overview",
])
svc("azure", "azure-docs", "cosmos-db", "database", [
    f"{Z}/cosmos-db/introduction",
    f"{Z}/cosmos-db/nosql/",
    f"{Z}/cosmos-db/partitioning-overview",
])
svc("azure", "azure-docs", "sql-database", "database", [
    f"{Z}/azure-sql/database/sql-database-paas-overview",
    f"{Z}/azure-sql/database/high-availability-sla",
])
svc("azure", "azure-docs", "cache-redis", "database", [
    f"{Z}/azure-cache-for-redis/cache-overview",
    f"{Z}/azure-cache-for-redis/cache-best-practices",
])
svc("azure", "azure-docs", "synapse", "analytics", [
    f"{Z}/synapse-analytics/overview-what-is",
])
svc("azure", "azure-docs", "data-factory", "analytics", [
    f"{Z}/data-factory/introduction",
])
# Networking
svc("azure", "azure-docs", "virtual-network", "networking", [
    f"{Z}/virtual-network/virtual-networks-overview",
    f"{Z}/virtual-network/concepts-and-best-practices",
])
svc("azure", "azure-docs", "application-gateway", "networking", [
    f"{Z}/application-gateway/overview",
])
svc("azure", "azure-docs", "front-door", "networking", [
    f"{Z}/frontdoor/front-door-overview",
    f"{Z}/frontdoor/best-practices",
])
svc("azure", "azure-docs", "azure-dns", "networking", [
    f"{Z}/dns/dns-overview",
])
svc("azure", "azure-docs", "expressroute", "networking", [
    f"{Z}/expressroute/expressroute-introduction",
])
svc("azure", "azure-docs", "load-balancer", "networking", [
    f"{Z}/load-balancer/load-balancer-overview",
])
# Security
svc("azure", "azure-docs", "entra-id", "security", [
    "https://learn.microsoft.com/en-us/entra/fundamentals/what-is-entra",
    "https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/custom-overview",
])
svc("azure", "azure-docs", "key-vault", "security", [
    f"{Z}/key-vault/general/overview",
    f"{Z}/key-vault/general/secure-key-vault",
])
svc("azure", "azure-docs", "defender", "security", [
    f"{Z}/defender-for-cloud/defender-for-cloud-introduction",
    f"{Z}/defender-for-cloud/secure-score-security-controls",
])
svc("azure", "azure-docs", "azure-policy", "security", [
    f"{Z}/governance/policy/overview",
])
svc("azure", "azure-docs", "azure-firewall", "security", [
    f"{Z}/firewall/overview",
])
svc("azure", "azure-docs", "sentinel", "security", [
    "https://learn.microsoft.com/en-us/azure/sentinel/overview",
])
# Observability
svc("azure", "azure-docs", "monitor", "observability", [
    f"{Z}/azure-monitor/fundamentals/overview",
    f"{Z}/azure-monitor/best-practices",
])
svc("azure", "azure-docs", "application-insights", "observability", [
    f"{Z}/azure-monitor/app/app-insights-overview",
])
svc("azure", "azure-docs", "log-analytics", "observability", [
    f"{Z}/azure-monitor/logs/log-analytics-overview",
])
# DevOps
svc("azure", "azure-docs", "azure-devops", "devops", [
    "https://learn.microsoft.com/en-us/azure/devops/user-guide/what-is-azure-devops",
])
svc("azure", "azure-docs", "bicep", "devops", [
    f"{Z}/azure-resource-manager/bicep/overview",
    f"{Z}/azure-resource-manager/bicep/best-practices",
])
svc("azure", "azure-docs", "arm-templates", "devops", [
    f"{Z}/azure-resource-manager/templates/overview",
    f"{Z}/azure-resource-manager/templates/best-practices",
])
svc("azure", "azure-docs", "container-registry", "devops", [
    f"{Z}/container-registry/container-registry-intro",
])
# Integration
svc("azure", "azure-docs", "api-management", "integration", [
    f"{Z}/api-management/api-management-key-concepts",
])
svc("azure", "azure-docs", "logic-apps", "integration", [
    f"{Z}/logic-apps/logic-apps-overview",
])
svc("azure", "azure-docs", "service-bus", "integration", [
    f"{Z}/service-bus-messaging/service-bus-messaging-overview",
])
svc("azure", "azure-docs", "event-hubs", "integration", [
    f"{Z}/event-hubs/event-hubs-about",
])
svc("azure", "azure-docs", "event-grid", "integration", [
    f"{Z}/event-grid/overview",
])
# AI/ML
svc("azure", "azure-docs", "ai-services", "ai-ml", [
    f"{Z}/ai-services/what-are-ai-services",
    f"{Z}/ai-foundry/openai/overview",
])


# ─────────────────────────── VALIDAÇÃO ───────────────────────────
def resolve(url):
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return url, r.status, r.geturl()
        except urllib.error.HTTPError as ex:
            if method == "HEAD" and ex.code in (400, 403, 405):
                continue
            return url, ex.code, None
        except Exception as ex:  # noqa
            return url, f"ERR:{type(ex).__name__}", None
    return url, "ERR", None


def all_urls():
    seen = []
    for scope in CATALOG:
        for cloud in CATALOG[scope]:
            for e in CATALOG[scope][cloud]:
                for u in e["urls"]:
                    seen.append((scope, cloud, e["service"], u))
    return seen


def validate():
    items = all_urls()
    urls = sorted({i[3] for i in items})
    res = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for url, status, final in ex.map(resolve, urls):
            res[url] = (status, final)
    bad = []
    for scope, cloud, service, url in items:
        status, final = res[url]
        ok = isinstance(status, int) and 200 <= status < 300
        if not ok:
            bad.append((cloud, service, url, status))
    return res, bad


def to_yaml(res):
    """Gera YAML manualmente, usando a URL final resolvida (canônica)."""
    lines = []
    lines.append("# Fontes de conhecimento por cloud, agrupadas por escopo de ingestão.")
    lines.append("#")
    lines.append("#   scope: mvp  -> apenas frameworks (Well-Architected / Architecture Framework)")
    lines.append("#   scope: full -> mvp + docs dos serviços principais")
    lines.append("#")
    lines.append("# Cada entrada vira metadados no cloud_docs (cloud, service, category, source, framework).")
    lines.append("# URLs validadas via scripts/build_sources.py (todas retornam HTTP 2xx).")
    lines.append("# ATENÇÃO: respeite os termos de uso / robots.txt de cada site ao coletar.")
    lines.append("")
    for scope in ("mvp", "full"):
        lines.append(f"{scope}:")
        for cloud in ("aws", "gcp", "azure"):
            entries = CATALOG[scope][cloud]
            if not entries:
                continue
            lines.append(f"  {cloud}:")
            for e in entries:
                lines.append(f"    - source: {e['source']}")
                if e.get("framework"):
                    lines.append(f"      framework: {e['framework']}")
                lines.append(f"      service: {e['service']}")
                lines.append(f"      category: {e['category']}")
                lines.append(f"      doc_type: {e['doc_type']}")
                lines.append("      urls:")
                for u in e["urls"]:
                    final = res.get(u, (None, None))[1] or u
                    lines.append(f"        - {final}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    res, bad = validate()
    total = len({i[3] for i in all_urls()})
    print(f"URLs candidatas únicas: {total}")
    print(f"Falhas (não-2xx): {len(bad)}\n")
    for cloud, service, url, status in bad:
        print(f"  [{status}] ({cloud}/{service}) {url}")

    if args.write and (not bad or args.force):
        OUT.write_text(to_yaml(res), encoding="utf-8")
        print(f"\nGravado: {OUT}")
    elif args.write:
        print("\nNÃO gravado: corrija as falhas ou use --force.")


if __name__ == "__main__":
    main()
