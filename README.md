<h1 align="center">Active Directory MCP</h1>

<p align="center">
  <strong>Multi-tenant Active Directory MCP Server &mdash; manage AD via AI assistants</strong>
</p>

<p align="center">
  <a href="https://github.com/DevSkillsIT/Skills-MCP-Active-Directory/stargazers"><img src="https://img.shields.io/github/stars/DevSkillsIT/Skills-MCP-Active-Directory?style=for-the-badge&color=000cd9" alt="Stars"/></a>
  <a href="https://github.com/DevSkillsIT/Skills-MCP-Active-Directory/network/members"><img src="https://img.shields.io/github/forks/DevSkillsIT/Skills-MCP-Active-Directory?style=for-the-badge&color=0a2463" alt="Forks"/></a>
  <a href="https://github.com/DevSkillsIT/Skills-MCP-Active-Directory/issues"><img src="https://img.shields.io/github/issues/DevSkillsIT/Skills-MCP-Active-Directory?style=for-the-badge&color=faad14" alt="Issues"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-52c41a?style=for-the-badge" alt="License"/></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/MCP-2024--11--05-blue?style=flat-square" alt="MCP Version"/>
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python" alt="Python"/>
  <img src="https://img.shields.io/badge/Transport-stdio_|_HTTP-orange?style=flat-square" alt="Transport"/>
  <img src="https://img.shields.io/badge/Tools-45-brightgreen?style=flat-square" alt="Tools"/>
</p>

<p align="center">
  <a href="#about">About</a> &bull;
  <a href="#multi-tenant-architecture">Architecture</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#tools">Tools</a> &bull;
  <a href="#configuration">Configuration</a> &bull;
  <a href="#security">Security</a>
</p>

---

## About

**Active Directory MCP** is an open-source [Model Context Protocol](https://modelcontextprotocol.io) server that lets AI assistants (Claude, Gemini CLI, ChatGPT via API, etc.) safely manage Active Directory environments.

### Key features

- **10 tools** covering users, groups, computers, OUs, security and the directory catalogue, plus 15 MSP prompt playbooks served through the MCP prompts protocol. One read-only `search_*` and one write `manage_*` per kind of object; the write tool takes an `action`. Common requests are one call each: an account's details already carry its groups, primary group and OU; onboarding copies groups and OU from a model account (`copy_from_user`); offboarding disables, moves (`move_to_ou`) and optionally strips groups in one call; membership calls accept lists.
- **Two transports, one catalogue**: stdio (`server.py`) is a thin adapter over the same registry, sanitizer, name resolution and deadlines that serve Streamable HTTP via FastAPI (`server_fastapi.py`). Neither transport can drift from the other. An earlier FastMCP-based HTTP transport (`server_http.py`) has been removed.
- **Two deployment modes**: `single` (default) binds one process to one AD via `AD_MCP_CONFIG` — run one process per tenant to serve several; `multi` binds one process to N ADs via `AD_MCP_SERVERS`, adding a required/optional `ad_server` parameter to every directory-bound tool. See [Multi-tenant architecture](#multi-tenant-architecture).
- **Write-operation guard rails**: every mutating tool requires either a per-tenant client confirmation string or an automation Bearer token before touching AD.
- **Audit log on every operation**: each call records operation name, target, mode (CONFIRMED / AUTOMATION / NO_CONFIRMATION_REQUIRED), and outcome.

### Naming convention

All MCP tool names use the `ad_*` prefix with a descriptive suffix &mdash; e.g. `ad_list_users_with_filters`, `ad_create_user_account`, `ad_disable_computer_account_trust`. This avoids collisions when this MCP runs alongside other servers (GLPI, Hudu, etc.) connected to the same AI client.

---

## Multi-tenant architecture

There are two ways to serve more than one AD with this codebase. Both read the same `active_directory` / `organizational_units` / `security` / `client` schema (see [Configuration](#configuration)); pick one per deployment, not both.

### Mode 1 &mdash; one process per tenant (`AD_MCP_MODE=single`, the default)

```
.base-code/                    <- this repository (shared source of truth)
  src/active_directory_mcp/
  ad-config/
    ad-config.example.json     <- template only (real configs are .gitignored)

<deployment>/                  <- one directory per tenant, OUTSIDE this repo
  tenant-a/
    ad-config/ad-config.json   <- real credentials (NEVER committed)
    start.sh                   <- exports AD_MCP_CONFIG and launches the server
  tenant-b/
    ad-config/ad-config.json
    start.sh
```

Each `start.sh` exports `AD_MCP_CONFIG` pointing at that tenant's config and runs `python -m active_directory_mcp.server_fastapi` on a dedicated port. Update the shared `.base-code/` once, restart every tenant process &mdash; same code, isolated state. Tools take no `ad_server` parameter in this mode; this is the original, unchanged behavior.

### Mode 2 &mdash; one process serving several ADs (`AD_MCP_MODE=multi`)

A single `server_fastapi.py` process can instead serve N directories, selected via `AD_MCP_SERVERS` pointing at an `ad-servers.json` (schema: [`ad-config/ad-servers.example.json`](ad-config/ad-servers.example.json) &mdash; each entry is an `ad-config.json` block plus `label`/`aliases`/`enabled`). Every directory-bound tool then gains an `ad_server` parameter:

- **Write tools**: `ad_server` is required and must name exactly one directory &mdash; there is no "all".
- **Read tools**: `ad_server` is optional; omitted (or `all`/`todos`/`*`) runs the query against every configured directory and the response reports where each result was found.
- **Catalog tool**: `ad_list_configured_clients`, `ad_check_client_configuration` and `ad_get_client_tenant_info` are replaced by a single `ad_list_ad_servers`, whose optional `server_name` resolves a name, alias, domain or client name to the exact `ad_server`. Calling it first is not required: `ad_server` itself accepts the client's name.

`ad_server` matching ignores case, accents and surrounding whitespace; a name that matches more than one directory is refused with the list of candidates rather than guessed. Write confirmation (`client_confirmation`, below) is validated against the same directory named by `ad_server`.

```bash
export AD_MCP_MODE=multi
export AD_MCP_SERVERS=/etc/ad-mcp/ad-servers.json
python -m active_directory_mcp.server_fastapi --host 0.0.0.0 --port 8820
```

The stdio transport (`server.py`) only supports single mode.

---

## Quick Start

### Prerequisites

- Python 3.11+
- LDAP/LDAPS reachable from the host
- An AD service account with the permissions required by the operations you plan to expose

### 1. Install

```bash
git clone https://github.com/DevSkillsIT/Skills-MCP-Active-Directory.git
cd Skills-MCP-Active-Directory

python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

pip install -e .                   # installs from pyproject.toml
```

### 2. Configure

```bash
mkdir -p /etc/ad-mcp
cp ad-config/ad-config.example.json /etc/ad-mcp/ad-config.json
$EDITOR /etc/ad-mcp/ad-config.json   # set server, bind_dn, password, base_dn, OUs
chmod 600 /etc/ad-mcp/ad-config.json
```

> The example file is the only template kept in git. Any real `ad-config.json` is blocked by `.gitignore` (`ad-config/*.json` + `!ad-config/*.example.json`).

### 3. Run

```bash
export AD_MCP_CONFIG=/etc/ad-mcp/ad-config.json

# stdio transport (for direct Claude Desktop / mcp-cli use):
python -m active_directory_mcp.server

# HTTP transport (for Claude Code, Gemini CLI, n8n, etc.):
python -m active_directory_mcp.server_fastapi --host 0.0.0.0 --port 8820
# MCP endpoint: http://localhost:8820/mcp   Health (no auth): http://localhost:8820/health
```

Set `AD_MCP_API_TOKEN` in the environment to require a Bearer token on the HTTP transport; without it the server accepts unauthenticated requests (development only &mdash; always set it in production). See [HTTP_MCP_GUIDE.md](HTTP_MCP_GUIDE.md) for the full transport reference, including the `multi` mode.

### 4. Connect from Claude Code

```bash
claude mcp add --transport http ad http://localhost:8820/mcp \
  --headers "Authorization: Bearer YOUR_AUTOMATION_TOKEN"
```

### 5. Connect from Gemini CLI

`~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "ad": {
      "httpUrl": "http://localhost:8820/mcp",
      "headers": { "Authorization": "Bearer YOUR_AUTOMATION_TOKEN" },
      "timeout": 30000
    }
  }
}
```

---

## Tools

Ten tools: one read-only `ad_search_*` and one write `ad_manage_*` per kind of
object, plus the catalogue. This is the house pattern (search = discovery,
manage = action through an `action` parameter) and it replaced the 38 verb-per-
tool names of before: the catalogue a client has to carry on every call went
from ~60k to ~23k characters, and a model no longer has to pick between seven
near-identical user tools.

Every tool declares MCP annotations: `ad_search_*` is `readOnlyHint: true`,
`ad_manage_*` is `destructiveHint: true` (every one of them includes `delete`).
In `multi` mode each tool bound to a directory also takes `ad_server`
(required on writes, optional on reads — omitted means every directory).

| Tool | Type | What it does |
|---|---|---|
| `ad_search_directory_servers` | read | Configured ADs; `server_name` resolves a client name; `test_connection` runs a live LDAP test (one or all) |
| `ad_search_directory_users` | read | `username` returns the full account sheet (groups, primary group, OU, flags, manager); otherwise lists by free text, LDAP filter or OU; `inactive_days` lists accounts without logon |
| `ad_manage_directory_users` | write | `action`: `create` (onboarding; `copy_from_user` copies groups and OU), `update`, `move`, `enable`, `disable` (offboarding with `move_to_ou` and `remove_from_groups`), `reset_password`, `delete` |
| `ad_search_directory_groups` | read | `group_name` returns the group with its members (`recursive` expands nested groups); otherwise lists |
| `ad_manage_directory_groups` | write | `action`: `create`, `update`, `move`, `add_members`, `remove_members` (several groups and members per call), `delete` |
| `ad_search_directory_computers` | read | `computer_name` returns the machine; otherwise lists; `inactive_days` lists stale machines |
| `ad_manage_directory_computers` | write | `action`: `create`, `update`, `move`, `enable`, `disable`, `reset_trust`, `delete` (a domain controller is refused) |
| `ad_search_organizational_units` | read | `ou_dn` returns the OU with its GPOs and its contents (`object_types` filters); otherwise lists the hierarchy |
| `ad_manage_organizational_units` | write | `action`: `create`, `update`, `move`, `delete` (`force` deletes the contents too) |
| `ad_search_security_reports` | read | `report`: `domain_policy`, `privileged_groups`, `admin_accounts`, `password_violations`, `user_permissions` |

Every write answer is read back from the directory (DN, account state, groups
actually joined), so a follow-up query to confirm it is unnecessary.

### Old tool names

The 38 names this server listed before are not gone: a client connected
directly (or a saved prompt) can still call them and is routed to the new tool
with the right `action` plus a `tool_unificada` note. A gateway that only
routes listed tools (mcphub) answers "tool not available" instead, and its
search then finds the new tool. The mapping lives in
`ALIASES_DE_TOOLS` (`server_fastapi.py`).

### MSP prompts (15)

The 15 professional MSP playbooks (7 manager + 8 analyst) are **not tools** &mdash; they are served through the standard MCP prompts protocol, `prompts/list` and `prompts/get`, over both transports. See [PROMPTS.md](PROMPTS.md) for the full catalog and usage.

---

## Configuration

The runtime configuration file path is provided via the `AD_MCP_CONFIG` environment variable. Schema in [`ad-config/ad-config.example.json`](ad-config/ad-config.example.json).

### Key fields

| Field | Required | Description |
|---|---|---|
| `active_directory.server` | yes | Primary LDAP URL, e.g. `ldaps://dc.example.com:636` |
| `active_directory.server_pool` | no | Additional LDAP URLs for failover |
| `active_directory.bind_dn` | yes | Full DN of the service account |
| `active_directory.password` | yes | Service account password (keep file at `chmod 600`) |
| `active_directory.base_dn` | yes | Base DN, e.g. `DC=example,DC=com` |
| `organizational_units.*` | yes | Default OUs for users/groups/computers/service accounts |
| `security.enable_tls` | no | Force StartTLS / LDAPS |
| `security.validate_certificate` | no | Verify server certificate against `ca_cert_file` |
| `security.require_secure_connection` | no | Refuse to bind over plaintext |
| `automation.token` | no | Bearer token for unattended write operations |
| `client.slug` | no | Tenant identifier reported by `ad_get_client_tenant_info` |

### Service account permissions

Grant the bind account the minimum delegated rights required by the operations you intend to expose:

- **Read-only deployments**: "Read all properties" + "List contents" on the domain root is enough.
- **User/group write**: delegate "Create/Delete objects" + "Write all properties" on the target OUs.
- **Password reset**: delegate the "Reset password" extended right on the target OUs.
- **Computer join/leave**: delegate "Create/Delete computer objects" on the computers OU.

Always use a dedicated service account, LDAPS in production, and rotate the password regularly.

---

## Security

### Write protection model

Every mutating tool (`ad_create_*`, `ad_modify_*`, `ad_delete_*`, `ad_enable_*`, `ad_disable_*`, `ad_reset_*`, `ad_add_*`, `ad_remove_*`, `ad_move_*`) calls `check_write_permission()` before reaching LDAP. It accepts the write if **one of**:

1. `automation_token` matches `automation.token` in the config &mdash; intended for CI / scheduled jobs.
2. `client_confirmation` matches the tenant slug &mdash; the AI assistant must identify the tenant first (`ad_get_client_tenant_info` in single mode, `ad_list_ad_servers` in multi mode), read the slug back to the user, and pass that exact string.
3. The tenant has `require_confirmation_for_writes: false` (explicit opt-out, not recommended).

If none of the above is satisfied, the call short-circuits with a `permitted: false` message and the LDAP write is never attempted.

### Audit logging

All operations write a structured log line including: timestamp, tool name, target, confirmation mode (`AUTOMATION` / `CONFIRMED` / `WRONG_CONFIRMATION` / `NO_CONFIRMATION_REQUIRED`), and success/failure. Logs go wherever `logging.file` points.

### Secrets hygiene

- Real `ad-config.json` files are git-ignored. Only `*.example.json` is tracked.
- Never paste a config containing a real `password` or `automation.token` into a chat that's logged or transcribed by a third party.
- Rotate `automation.token` whenever you regenerate it; treat it as a privileged credential.

---

## Testing

```bash
# Unit + integration tests
pytest tests/ -v

# Coverage
pytest --cov=src/active_directory_mcp --cov-report=term-missing

# Lint
ruff check .
```

A bundled `docker-compose-ad.yml` spins up a Samba AD container at `192.168.1.100` plus an MCP container so the integration tests can run against a real LDAP backend without touching production.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `LDAP bind failed` | bad `bind_dn` / `password` | Verify against `ldapsearch -H <server> -D '<bind_dn>' -W` |
| `Insufficient permissions` | service account lacks delegated rights | Re-delegate on the target OU |
| `Certificate verification failed` | self-signed cert without trust | Set `ca_cert_file` or `validate_certificate: false` (test only) |
| `permitted: false` on every write | Missing confirmation/token | Identify the tenant first (`ad_get_client_tenant_info` / `ad_list_ad_servers`), or pass `automation_token` |
| `Health degraded` | socket open but LDAP search failed | Check service-account lockout / replication / network ACLs |

---

## Contributing

1. Fork the repo.
2. Create a feature branch: `git checkout -b feat/your-feature`.
3. Run tests: `pytest`.
4. Open a PR with a clear description and a link to the relevant issue.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/).

---

## License

MIT &mdash; see [LICENSE](LICENSE).

## Acknowledgments

- Based on the upstream [`alpadalar/ActiveDirectoryMCP`](https://github.com/alpadalar/ActiveDirectoryMCP) project by Alperen Adalar.
- Built on top of [`mcp`](https://github.com/modelcontextprotocol/python-sdk), [`fastmcp`](https://github.com/jlowin/fastmcp), [`ldap3`](https://github.com/cannatag/ldap3), and FastAPI.

## Support

- Bug reports: [GitHub Issues](https://github.com/DevSkillsIT/Skills-MCP-Active-Directory/issues)
- Discussions: [GitHub Discussions](https://github.com/DevSkillsIT/Skills-MCP-Active-Directory/discussions)
