# Database ER diagram (MVP tables)

Every tenant table also has `org_id -> organizations.id`. Child tables reference parents with a
composite key `(parent_id, org_id)`, so a row can never point at another organization's data.
`tools` is a global catalog (no `org_id`). `audit_logs` is append-only for the runtime role.

```mermaid
erDiagram
    users ||--o{ organization_members : "joins"
    organizations ||--o{ organization_members : "has"
    organizations ||--o{ agents : "owns"
    agents ||--o{ agent_versions : "has versions"
    agents ||--o| agent_versions : "current_version"
    agent_versions ||--o{ agent_tools : "allows"
    tools ||--o{ agent_tools : "granted via"
    organizations ||--o{ integrations : "connects"
    integrations ||--o{ credentials : "secured by"
    agents ||--o{ agent_runs : "executes"
    agent_versions ||--o{ agent_runs : "run with"
    agent_runs ||--o{ run_steps : "logs"
    agent_runs ||--o{ approvals : "pauses for"
    run_steps ||--o{ approvals : "raised by"
    agents ||--o{ conversations : "chats"
    conversations ||--o{ messages : "contains"
    agent_runs ||--o{ messages : "produces"
    agent_runs ||--o{ usage_records : "costs"
    organizations ||--o{ audit_logs : "audited"
    users ||--o{ audit_logs : "acts"

    users { uuid id PK; string email UK; bool is_super_admin }
    organizations { uuid id PK; string name; string slug UK }
    organization_members { uuid id PK; uuid org_id FK; uuid user_id FK; string role }
    agents { uuid id PK; uuid org_id FK; string name; string status; uuid current_version_id FK; timestamp deleted_at }
    agent_versions { uuid id PK; uuid agent_id FK; int version; text system_instructions; string model; jsonb limits }
    tools { uuid id PK; string key UK; jsonb input_schema; bool is_sensitive }
    agent_tools { uuid id PK; uuid agent_version_id FK; uuid tool_id FK; bool requires_approval }
    integrations { uuid id PK; uuid org_id FK; string provider; string name }
    credentials { uuid id PK; uuid integration_id FK; bytes encrypted_payload }
    agent_runs { uuid id PK; uuid agent_id FK; uuid agent_version_id FK; string status; string idempotency_key; numeric cost_usd }
    run_steps { uuid id PK; uuid run_id FK; int sequence; string step_type; string status }
    approvals { uuid id PK; uuid run_id FK; string tool_key; jsonb proposed_input; string status }
    conversations { uuid id PK; uuid agent_id FK; uuid user_id FK }
    messages { uuid id PK; uuid conversation_id FK; string role; jsonb content }
    usage_records { uuid id PK; uuid run_id FK; string model; int input_tokens; int output_tokens; numeric cost_usd }
    audit_logs { uuid id PK; uuid org_id FK; uuid actor_user_id FK; string action }
```

Later phases add: `organization_invitations`, `workflows`, `workflow_versions`, `triggers`,
`scheduled_jobs`, `knowledge_bases`, `documents`, `document_chunks`, `subscriptions`.
