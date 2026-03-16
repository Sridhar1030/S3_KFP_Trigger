<!--
Sync Impact Report:
- Version change: INITIAL → 1.0.0
- New constitution initialization
- Principles defined:
  1. Event-Driven Architecture
  2. Layer Isolation & Testability
  3. Integration-First Development
  4. Enterprise Reusability
  5. Security & Authentication First
- Templates status:
  ✅ constitution-template.md (source template)
  ⚠ plan-template.md (pending alignment review)
  ⚠ spec-template.md (pending alignment review)
  ⚠ tasks-template.md (pending alignment review)
- Follow-up TODOs: None
-->

# S3-KFP Trigger Constitution

## Core Principles

### I. Event-Driven Architecture
Every component MUST respond to events, not polling or manual invocation.

- S3 bucket events (ObjectCreated) are the single source of truth for pipeline triggers
- Webhooks deliver events to OpenShift Tekton EventListeners
- Event payloads MUST include bucket name, object key, and timestamp
- No cron jobs or scheduled triggers for data-driven pipelines

**Rationale**: Event-driven design eliminates manual bottlenecks, reduces latency between data
arrival and processing, and ensures the system scales naturally with data volume.

### II. Layer Isolation & Testability
Each integration layer MUST be independently testable without dependencies on upstream systems.

- **Layer 1 (KFP Pipeline)**: Accepts `s3_uri` parameter, runs standalone
- **Layer 2 (Trigger Script)**: Python script using KFP SDK, testable with mock pipelines
- **Layer 3 (Tekton EventListener)**: Processes webhook payloads, testable with curl/httpie
- **Layer 4 (S3 Integration)**: Webhook configuration, testable with manual uploads

Each layer MUST have:
- Clear input/output contracts
- Sample payloads for testing
- Failure modes documented
- Rollback procedures defined

**Rationale**: Bottom-up testing ensures each component works before integration. This prevents
debugging nightmares where failures cascade across multiple systems.

### III. Integration-First Development
Build backward from the target system (Kubeflow) to the event source (S3).

**Mandatory sequence**:
1. Create and validate KFP pipeline locally
2. Develop trigger script and test against RHOAI
3. Deploy Tekton EventListener and test with manual webhook calls
4. Connect S3 bucket webhook as final step

**Rules**:
- Never connect S3 webhooks until Tekton → KFP flow is proven
- Always have a working component to test against
- Document integration points with sample requests/responses
- Maintain curl/httpie test scripts for each layer

**Rationale**: Working backward ensures you always have a known-good target. Forward integration
would leave you debugging whether the problem is in S3, Tekton, or Kubeflow simultaneously.

### IV. Enterprise Reusability
This project MUST serve as a reference architecture, not a one-off hack.

**Requirements**:
- All code in version control with clear directory structure
- Template YAML files for Tekton TriggerBinding, TriggerTemplate, EventListener
- Parameterized configurations (namespace, bucket, pipeline name)
- README with architectural diagram showing event flow
- Troubleshooting guide with common failure scenarios

**Deliverables**:
- Git repository as "MLOps Event-Driven Trigger Pattern"
- 60-second demo video showing end-to-end flow
- Architecture decision records (ADRs) for key choices

**Rationale**: Enterprise patterns require documentation and reusability. A successful PoC that
can't be replicated or explained has limited value.

### V. Security & Authentication First
Authentication and authorization MUST be explicit, never bypassed or hardcoded.

**Security requirements**:
- Service accounts for Tekton → KFP communication
- RBAC policies documented and version-controlled
- No credentials in code or logs
- TLS/HTTPS for all webhook endpoints
- S3 webhook signatures validated (if supported)

**Authentication flow**:
1. S3 webhook → Tekton EventListener (authenticated via OpenShift Route)
2. Tekton Task → KFP API (service account token)
3. KFP Pipeline → S3 data access (pod-level IAM or access keys in secrets)

**Rationale**: Security bypasses are technical debt that block production deployment. Building
auth correctly from day one prevents painful retrofitting.

## Technology Stack Constraints

**Required platforms**:
- OpenShift 4.x (for Tekton Pipelines)
- Red Hat OpenShift AI (RHOAI) with Kubeflow Pipelines
- S3-compatible storage (AWS S3, MinIO, or OpenShift Data Foundation)

**Required tooling**:
- Python 3.9+ with `kfp` SDK
- `oc` CLI for OpenShift operations
- `kubectl` for Kubernetes resources
- curl/httpie for webhook testing

**Forbidden**:
- Custom webhook listeners (use Tekton EventListener exclusively)
- Long-running services for event processing (use Tekton Tasks)
- Polling mechanisms or cron-based triggers for data events

## Development Workflow

**Task-based execution** (not time-based):
- Break work into atomic, testable tasks
- Each task MUST have clear acceptance criteria
- Tasks proceed only when previous layer validated
- No parallel work on dependent layers

**Quality gates**:
1. **Layer validation**: Component works in isolation
2. **Integration validation**: Two layers communicate successfully
3. **End-to-end validation**: Full S3 → KFP flow completes
4. **Documentation validation**: README includes working examples

**Review process**:
- All YAML manifests peer-reviewed before deployment
- Security configurations reviewed by platform team
- Demo video validated before presenting to stakeholders

## Governance

This constitution defines the non-negotiable architectural and process requirements for the
S3-KFP Trigger project. All implementation decisions MUST align with these principles.

**Amendments**:
- Constitution changes require documented justification
- Version bump follows semantic versioning
- All dependent templates updated within same commit

**Compliance**:
- Every task references applicable principle(s)
- Code reviews verify principle adherence
- Architecture deviations require explicit ADR

**Version**: 1.0.0 | **Ratified**: 2026-03-16 | **Last Amended**: 2026-03-16
