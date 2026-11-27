# HTTP tools

Two tools let an agent call web APIs. Both need an **HTTP integration**, which holds the list of
hosts the agent may call and, optionally, the secret (API key) to send. See `docs/credentials.md`
for how secrets are stored.

| Tool | Does | Approval |
| --- | --- | --- |
| `http.get` | GET a URL and return its text or JSON | No |
| `http.request` | POST, PUT, PATCH or DELETE, and return the reply | Always (sensitive): the run pauses until a person approves it (`docs/approvals.md`). |

## Setting it up

1. **Integrations tab:** add an *HTTP / API* integration. List the allowed hosts (one per line,
   such as `api.example.com`), say how the secret is sent (default `Authorization: Bearer <secret>`;
   leave the prefix empty for headers like `X-API-Key`), and optionally save the secret.
2. **Agent form:** tick *HTTP GET*. Choose the integration (chosen for you if only one fits).
3. An agent version saves only if the integration exists in the organization, is an HTTP
   integration and is active. The grant's settings are exactly `{"integration_id": "<uuid>"}`.

## What the agent can send

`http.get`: `url` and optional `headers` (a list of `{name, value}`).

`http.request`: `method`, `url`, optional `headers`, `body` (text; for JSON pass the JSON as a
string) and `content_type` (`application/json` by default, or `text/plain` or
`application/x-www-form-urlencoded`).

## Rules enforced on every call

| Rule | Detail |
| --- | --- |
| Hosts | Only exact host names on the integration's list. An empty list allows nothing. Read from the integration at call time, so an admin's edit applies to saved agents immediately. |
| URL | `https` only, standard port 443 only, no `user:pass@`, no IP addresses, ASCII only, at most 2,000 characters. |
| Retries | A write (POST, PUT, PATCH, DELETE) carries an `Idempotency-Key` header naming that one call; it is the same if the call is ever carried out again after a crash, so services that honour the header recognise the repeat. Agents cannot set it themselves. The platform never repeats a write that had started. |
| Where it really goes | The platform resolves the host itself and every address must be public. Loopback, private ranges, link-local (including the cloud metadata address 169.254.169.254), shared/CGNAT space, multicast, reserved, IPv6 unique-local and IPv6 forms that wrap an IPv4 address are refused. The connection goes to the address that was checked, so a DNS answer that changes in between cannot reach an internal address. |
| TLS | Certificates are verified against the host name in the URL. |
| Headers | The agent cannot set Host, Authorization, Cookie, connection or proxy headers, `Sec-*`, forwarded-for headers, or the integration's own credential header. At most 10 headers; values are plain ASCII without line breaks. |
| Credential | Added by the platform, never by the agent, and sent only to the host first called (never to a redirect target on another host). |
| Redirects | `http.get` follows at most 3, each re-checked against every rule above. `http.request` follows none: the 3xx reply is returned and a new request needs a new approval. |
| Size and time | 20 seconds overall; request body up to 100 KB; response read as a stream and cut at 1 MB (`truncated: true`). |
| Response type | Text and JSON only (`text/*`, JSON, XML). Images, other binary data and compressed replies (`Accept-Encoding: identity` is sent) come back as a short refusal, never as bytes. |
| Untrusted output | Every reply carries a `notice` saying the body is untrusted data, never instructions. |
| Secret scrubbing | If the remote server echoes the credential, it is replaced with `[redacted]` before the reply reaches the model or the run record. |

An HTTP error status (404, 500...) is **returned** to the model with its body so it can react; the
tool only raises an error for refusals and network failures, with a plain message.

## Where the code is

- `app/tools/netsafety.py`: address rules, URL checks, `SafeNetworkBackend`.
- `app/tools/http.py`: the two handlers, header and body checks, redirects, response limits.
- `app/tools/integration_access.py`: loads the integration and decrypts the secret for one call.
- Tests: `tests/test_netsafety.py` and `tests/test_http_tool.py` (a local HTTPS server with a real
  certificate, no internet), `tests/integration/test_http_tool_engine.py` (a whole run) and
  `tests/integration/test_agent_tool_integrations.py` (saving agents).

## Limits worth knowing

- The platform does not use proxy environment variables for these calls.
- A host that serves a certificate for another name is refused even if an admin listed it.
- Two integrations never share allowed hosts: each tool grant is tied to exactly one integration.
