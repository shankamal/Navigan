# Navigan Application Flow

## End-to-end architecture

```mermaid
flowchart LR
    engineer["Cloud Engineer"]
    architect["Platform Architect"]
    cognito["Amazon Cognito"]
    portal["Next.js Navigan portal"]
    gateway["Amazon API Gateway"]
    customer["Customer Management Lambda"]
    environment["Environment Management Lambda"]
    cluster["Cluster Management Lambda"]
    database[("Aurora PostgreSQL")]
    codebuild["CodeBuild Terraform runner"]
    artifacts[("Encrypted S3 plan and state artifacts")]
    eventbridge["EventBridge build events"]
    status["Terraform status Lambda"]
    customerAws["Customer AWS account"]

    engineer -->|"Sign in"| cognito
    architect -->|"Sign in"| cognito
    cognito -->|"JWT access token"| portal
    portal -->|"Bearer JWT"| gateway

    gateway -->|"Customer routes"| customer
    gateway -->|"Environment routes"| environment
    gateway -->|"Cluster routes"| cluster

    customer -->|"Customers, reviews and audit"| database
    environment -->|"Profiles, versions and discovery selections"| database
    cluster -->|"Requests, workflow and plan status"| database

    cluster -->|"Approval starts Terraform plan"| codebuild
    codebuild -->|"Store immutable plan and SHA-256"| artifacts
    codebuild -->|"Assume NaviganProvisioningRole"| customerAws
    codebuild -->|"Completion event"| eventbridge
    eventbridge -->|"Invoke"| status
    status -->|"Update certification and execution status"| database
```

## Governed business workflow

```mermaid
flowchart TD
    login["User signs in through Cognito"]
    role{"Assigned role"}

    customerDraft["Cloud Engineer creates customer draft"]
    customerSubmit["Submit customer"]
    customerReview["Platform Architect reviews"]
    customerActive["Approve and activate customer"]

    environmentDraft["Cloud Engineer creates environment profile"]
    discovery["Discover AWS account resources"]
    blueprint["Select baseline and define cluster blueprints"]
    environmentSubmit["Submit environment"]
    environmentReview["Platform Architect reviews"]
    environmentActive["Approve and activate environment"]

    clusterDraft["Cloud Engineer creates cluster setup request"]
    clusterSubmit["Submit cluster request"]
    clusterReview["Platform Architect reviews request"]
    clusterApprove["Approve request"]
    plan["Generate immutable Terraform plan"]
    certify{"Validation and security checks pass?"}
    correct["Correct environment blueprint or configuration"]
    confirm["Architect confirms exact plan hash"]
    apply["Apply certified Terraform plan"]
    eks["EKS cluster and node groups provisioned"]

    login --> role
    role -->|"Cloud Engineer"| customerDraft
    customerDraft --> customerSubmit
    customerSubmit --> customerReview
    customerReview --> customerActive

    customerActive --> environmentDraft
    environmentDraft --> discovery
    discovery --> blueprint
    blueprint --> environmentSubmit
    environmentSubmit --> environmentReview
    environmentReview --> environmentActive

    environmentActive --> clusterDraft
    clusterDraft --> clusterSubmit
    clusterSubmit --> clusterReview
    clusterReview --> clusterApprove
    clusterApprove --> plan
    plan --> certify
    certify -->|"No"| correct
    correct --> environmentDraft
    certify -->|"Yes"| confirm
    confirm --> apply
    apply --> eks
```

## Primary API groups

| API group | Main responsibility |
|---|---|
| `/api/v1/customers` | Customer onboarding, review, approval, activation and audit |
| `/api/v1/environments` | Cloud discovery, reusable environment profiles, versioning and activation |
| `/api/v1/clusters` | Cluster setup requests, architecture review, Terraform planning and apply |

