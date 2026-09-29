"""Test-wide isolation from the operator's environment.

Discovered by running the suite in a shell where multi/.env had been sourced:
test_http_server_initialization builds a server without passing `mode`, so it
read AD_MCP_MODE=multi and AD_MCP_SERVERS from the environment and loaded the
eight real customer directories. A unit test must never depend on -- let alone
reach -- production, and whether it does must not hinge on which shell ran it.

test_smoke_ao_vivo.py is the deliberate exception: it reads AD_MCP_API_TOKEN
before this fixture applies (at import time) and skips itself when absent.
"""

import pytest

VARIAVEIS_DE_AMBIENTE = (
    "AD_MCP_MODE",
    "AD_MCP_CONFIG",
    "AD_MCP_SERVERS",
    "AD_MCP_LOG_LEVEL",
    "AD_MCP_LOG_FILE",
)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch, request):
    """Every test starts without AD_MCP_* leaking in from the shell."""
    if request.node.fspath.basename == "test_smoke_ao_vivo.py":
        return
    for nome in VARIAVEIS_DE_AMBIENTE:
        monkeypatch.delenv(nome, raising=False)


@pytest.fixture
def srv(tmp_path):
    """The whole multi-AD server over a stateful fake directory.

    Name resolution, sanitizing and routing all run for real; only LDAP is
    replaced. Shared by the one-call-flow and write-audit test files.
    """
    from active_directory_mcp.server_fastapi import ActiveDirectoryMCPFastAPI

    from .diretorio_falso import BASE, diretorio_padrao, grupo
    from .test_fluxos_de_uma_chamada import G_FIN, G_TI, SABRINA, SID
    from .test_resolucao_de_identificadores import _TOOLSETS, _config_multi

    servidor = ActiveDirectoryMCPFastAPI(port=0, servers_path=_config_multi(tmp_path),
                                         mode="multi")
    bundle, erro = servidor.pool.resolve_or_error("alfa")
    assert erro is None, erro
    falso = diretorio_padrao()
    dn_users, attrs_users = grupo("Domain Users", "Domain Users", f"CN=Users,{BASE}")
    attrs_users["objectSid"] = f"{SID}-513"
    falso.entradas.append(type(falso.entradas[0])(dn_users, attrs_users))
    for entrada in falso.entradas:
        classes = entrada.atributos.get("objectClass") or []
        if "user" in classes and "computer" not in classes:
            entrada.atributos["primaryGroupID"] = 513
            entrada.atributos["objectSid"] = f"{SID}-{1100 + len(entrada.dn)}"
    falso.incluir_membro(G_FIN, SABRINA)
    falso.incluir_membro(G_TI, SABRINA)
    bundle.ldap_manager = falso
    for nome in _TOOLSETS:
        getattr(bundle, nome).ldap = falso
    servidor.falso = falso
    return servidor
