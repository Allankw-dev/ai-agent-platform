# Credentials and integrations

An **integration** is a connection to an outside service (HTTP APIs, Slack for now). Its non-secret
settings live in `integrations.config`; its secret (an API key or bot token) is stored encrypted in
`credentials`, one per integration. A secret can be **written but never read back**.

## Setup

Generate a key once, put it in `.env` as `CREDENTIAL_ENCRYPTION_KEY`, and recreate the containers:

```
docker compose exec api python -m app.core.vault
docker compose up -d --force-recreate api worker
```

- Keep the key only in `.env` (never in git). Back it up somewhere safe: **if it is lost or changed,
  saved secrets cannot be decrypted** and must be entered again. There is no key rotation yet;
  `credentials.key_version` exists so one can be added later.
- Without a key the platform starts normally. Integrations can be listed and edited, but saving a
  secret answers `503 credentials_not_configured` with a message saying what to do.

## How a secret is stored

AES-256-GCM (`cryptography`). The stored value is a random 12-byte nonce followed by the ciphertext
and authentication tag. The organization id, integration id and key version are bound into the
encryption (associated data), so:

- a value copied onto another integration, or into another organization, does not decrypt;
- any changed byte, or a different key, fails to decrypt.

## Who can do what

| | Owner | Admin | Developer | Member |
| --- | :-: | :-: | :-: | :-: |
| List integrations, see "a secret is saved by X on <date>" | yes | yes | yes | no |
| Add, edit, disable, delete; save, replace or remove a secret | yes | yes | no | no |

Another organization's integration answers `404`, like every other tenant resource.

## API

All under `/api/v1/organizations/{org_id}/integrations`:

| Call | Does |
| --- | --- |
| `GET ""`, `GET /{id}` | List (filter `provider`, paged) or read. Shows `has_credential`, `credential_set_by_name`, `credential_updated_at`. Never the secret. |
| `POST ""` | `{provider, name, config}`. Names are unique per provider. `provider_not_supported`, `invalid_integration_config` (422), `integration_name_taken` (409). |
| `PATCH /{id}` | Change `name`, `status` (`active` or `disabled`) or `config`. |
| `PUT /{id}/credential` | `{secret}`. Saves or replaces. |
| `DELETE /{id}/credential` | Removes the secret. |
| `DELETE /{id}` | Deletes the integration and its secret. |

## Rules that keep secrets secret

1. Only `app/services/credentials.py` decrypts (`reveal_secret`), and the only caller is
   `app/tools/integration_access.py`, which hands the secret to a running tool call in an object
   whose repr hides it. Tests read the source to enforce this.
2. No response model has a field for a secret. Validation errors for the credential route drop the
   submitted value (FastAPI would otherwise echo it back as `input`).
3. The audit log records who and when (`credential.added|replaced|removed`), never the value.
4. Log fields named like `token`, `secret`, `authorization`, `password`, `api_key`, `credential` or
   `cookie` are replaced with `[redacted]` before anything is printed.
5. Tool code must pass a tool's output through `app.core.vault.redact_secret` before it is recorded
   in a run step or returned to the model, in case the remote service echoes the credential.
6. Never put a secret in `config`: that column is shown to developers and returned by the API.
