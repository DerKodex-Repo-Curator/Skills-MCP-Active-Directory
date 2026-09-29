"""Descriptions are part of the contract: they decide what the model sends.

The production incident behind this file: ad_get_user_details_by_username said
"busca ... por username (sAMAccountName)", every write tool said "confirme
cliente primeiro", and the stdio server kept its own drifting copy of all of
them. The model believed both, asked the operator for a login it did not need
and for a confirmation code the server no longer required.
"""

import asyncio
import json
import logging
import re
from types import SimpleNamespace

import pytest
from mcp.server.lowlevel import Server

from active_directory_mcp import server as stdio
from active_directory_mcp.core.resolver import LISTAGENS, NOMES_NOVOS, PARAMETROS_RESOLVIDOS
from active_directory_mcp.server_fastapi import ActiveDirectoryMCPFastAPI
from active_directory_mcp.tools.computer import ComputerTools
from active_directory_mcp.tools.definitions import (
    DESCRICOES_PARAMETROS,
    DESCRICOES_TOOLS,
    INSTRUCOES_DO_SERVIDOR,
)
from active_directory_mcp.tools.group import GroupTools
from active_directory_mcp.tools.organizational_unit import OrganizationalUnitTools
from active_directory_mcp.tools.security import SecurityTools
from active_directory_mcp.tools.user import UserTools

from .diretorio_falso import BASE, diretorio_padrao


def _registro_http(multi: bool):
    srv = ActiveDirectoryMCPFastAPI.__new__(ActiveDirectoryMCPFastAPI)
    srv.multi, srv.pool, srv.security_manager = multi, None, None
    srv.logger = logging.getLogger("teste")
    for nome in ActiveDirectoryMCPFastAPI._TENANT_ATTRS:
        setattr(srv, nome, None)
    srv._build_tool_registry()
    return srv.tools


def _servidor_stdio(ldap=None):
    """The stdio transport over the shared catalogue (no second registry)."""
    srv = stdio.ActiveDirectoryMCPServer.__new__(stdio.ActiveDirectoryMCPServer)
    nucleo = ActiveDirectoryMCPFastAPI.__new__(ActiveDirectoryMCPFastAPI)
    nucleo.multi, nucleo.pool, nucleo.security_manager = False, None, None
    nucleo.logger = logging.getLogger("teste")
    nucleo.config = SimpleNamespace(
        active_directory=SimpleNamespace(base_dn=BASE, domain="alfa.local"))
    nucleo.ldap_manager = ldap
    nucleo.user_tools = UserTools(ldap) if ldap else None
    nucleo.group_tools = GroupTools(ldap) if ldap else None
    nucleo.computer_tools = ComputerTools(ldap) if ldap else None
    nucleo.ou_tools = OrganizationalUnitTools(ldap) if ldap else None
    nucleo.security_tools = SecurityTools(ldap) if ldap else None
    nucleo._build_tool_registry()
    srv.nucleo = nucleo
    srv.logger = nucleo.logger
    srv.app = Server("ActiveDirectoryMCP")
    srv._registrar()
    return srv


def _chamar_stdio(srv, nome, argumentos):
    resposta = asyncio.run(srv.nucleo.handle_tools_call(
        {"name": nome, "arguments": argumentos}))
    return json.loads(resposta["content"][0]["text"])


TODAS_HTTP = {**_registro_http(False), **_registro_http(True)}


# ----------------------------------------------------------- tool descriptions

@pytest.mark.parametrize("nome", sorted(TODAS_HTTP))
def test_descricao_segue_as_diretrizes(nome):
    texto = TODAS_HTTP[nome]["description"]
    assert texto == DESCRICOES_TOOLS[nome]
    assert 280 <= len(texto) <= 400, (nome, len(texto))
    assert len(re.findall(r"\bAD\b|Active Directory", texto)) >= 2
    assert "Use quando" in texto or "Use somente quando" in texto
    assert "confirme cliente" not in texto.lower()


def test_nao_ha_descricao_sobrando_nem_faltando():
    assert set(DESCRICOES_TOOLS) == set(TODAS_HTTP)


@pytest.mark.parametrize("nome", sorted(n for n, t in TODAS_HTTP.items()
                                        if set(t["inputSchema"].get("properties", {}))
                                        & set(PARAMETROS_RESOLVIDOS)
                                        and n not in NOMES_NOVOS))
def test_tool_que_localiza_objeto_diz_que_aceita_nome(nome):
    assert "nome" in TODAS_HTTP[nome]["description"].lower()


# ------------------------------------------------------ parameter descriptions

@pytest.mark.parametrize("nome", sorted(TODAS_HTTP))
def test_todo_parametro_tem_descricao_em_portugues(nome):
    for parametro, spec in TODAS_HTTP[nome]["inputSchema"].get("properties", {}).items():
        if parametro == "ad_server":
            continue
        texto = spec.get("description") or ""
        assert texto, f"{nome}.{parametro} sem descricao"
        assert not re.search(r"\b(the|to retrieve|distinguished name|filter criteria)\b",
                             texto, re.I), f"{nome}.{parametro} em ingles: {texto}"


@pytest.mark.parametrize("parametro", sorted(set(PARAMETROS_RESOLVIDOS) - {"object_name"}))
def test_parametro_de_identificador_diz_as_formas_aceitas(parametro):
    texto = DESCRICOES_PARAMETROS[parametro].lower()
    assert "nome" in texto and ("dn" in texto or "caminho" in texto)


def test_enum_declarado_onde_o_valor_e_fechado():
    props = TODAS_HTTP["ad_manage_directory_groups"]["inputSchema"]["properties"]
    assert props["group_scope"]["enum"] == ["Global", "DomainLocal", "Universal"]
    assert props["group_type"]["enum"] == ["Security", "Distribution"]


@pytest.mark.parametrize("nome", sorted(n for n in TODAS_HTTP if "_manage_" in n))
def test_manage_declara_as_actions_no_enum_e_na_descricao(nome):
    """The action is the whole contract of a manage_* tool: a value missing
    from the enum cannot be called, and one missing from the parameter text is
    invisible to the model."""
    props = TODAS_HTTP[nome]["inputSchema"]["properties"]
    acoes = props["action"]["enum"]
    assert acoes == ActiveDirectoryMCPFastAPI.ACOES[nome]
    texto = props["action"]["description"]
    for a in acoes:
        assert a in texto, (nome, a)
        assert (nome, a) in ActiveDirectoryMCPFastAPI.REQUISITOS_POR_ACAO, (nome, a)


# ------------------------------------------------ hand-kept lists in the resolver

def test_toda_tool_de_criacao_declara_o_nome_novo():
    # A create tool missing from NOMES_NOVOS would look up the object it is
    # about to create, find nothing, and refuse to create it.
    for nome, tool in TODAS_HTTP.items():
        if "_create_" not in nome:
            continue
        props = set(tool["inputSchema"].get("properties", {}))
        identificadores = props & {"username", "group_name", "computer_name"}
        if identificadores:
            assert NOMES_NOVOS.get(nome) in identificadores, nome


def test_toda_listagem_com_filtro_aceita_texto_livre():
    for nome, tool in TODAS_HTTP.items():
        if "filter_criteria" in tool["inputSchema"].get("properties", {}):
            assert nome in LISTAGENS, nome


# ------------------------------------------------------------- stdio transport

def test_stdio_lista_exatamente_o_catalogo_compartilhado():
    """One registry, two transports: stdio can no longer drift from HTTP."""
    srv = _servidor_stdio()
    http = _registro_http(False)
    listadas = {t.name: t for t in srv._tools()}
    assert set(listadas) == {n for n, t in http.items() if not t.get("oculta")}
    for nome, tool in listadas.items():
        assert tool.description == DESCRICOES_TOOLS[nome], nome
        assert tool.inputSchema == http[nome]["inputSchema"], nome
        assert tool.annotations.readOnlyHint is nome.startswith("ad_search_"), nome


def test_stdio_move_aceita_objeto_por_nome():
    srv = _servidor_stdio()
    props = srv.nucleo.tools["ad_move_organizational_unit_parent"]["inputSchema"]["properties"]
    assert {"object_name", "object_type", "ou_dn", "new_parent_dn"} <= set(props)


def test_stdio_resolve_nome_completo():
    srv = _servidor_stdio(diretorio_padrao())
    corpo = _chamar_stdio(srv, "ad_search_directory_users",
                          {"username": "Sabrina De Moura Lopes Rocha"})
    assert "sabrina.rocha" in json.dumps(corpo, ensure_ascii=False)
    assert corpo["identificacao"][0]["resolvido_para"] == "sabrina.rocha"


def test_stdio_ambiguo_nao_executa():
    srv = _servidor_stdio(diretorio_padrao())
    corpo = _chamar_stdio(srv, "ad_manage_directory_users",
                          {"action": "disable", "username": "João"})
    assert corpo["erro"] == "IDENTIFICACAO_AMBIGUA"


def test_stdio_aceita_o_nome_antigo_da_tool():
    srv = _servidor_stdio(diretorio_padrao())
    corpo = _chamar_stdio(srv, "ad_get_user_details_by_username",
                          {"username": "sabrina.rocha"})
    assert "ad_search_directory_users" in corpo["tool_unificada"]


# ---------------------------------------------------------- server instructions

def test_initialize_publica_as_instrucoes():
    srv = ActiveDirectoryMCPFastAPI.__new__(ActiveDirectoryMCPFastAPI)
    r = asyncio.run(srv.handle_initialize({}))
    assert r["instructions"] == INSTRUCOES_DO_SERVIDOR
    assert "login" in r["instructions"] and "candidatos" in r["instructions"]


# ------------------------------------------------ achados 8 e 11 da auditoria

_ACOES = ("Criação", "Exclusão", "Reativação", "Desativação", "Redefinição", "Inclusão",
          "Remoção", "Movimentação", "Verificação", "Auditoria", "Atualização")


@pytest.mark.parametrize("nome", sorted(DESCRICOES_TOOLS))
def test_substantivo_chave_vem_primeiro(nome):
    # DIRETRIZES 3.4: the resource opens the text, not the action on it.
    assert DESCRICOES_TOOLS[nome].split()[0] not in _ACOES


def test_object_types_declara_os_valores():
    spec = TODAS_HTTP["ad_search_organizational_units"]["inputSchema"]["properties"]
    itens = [a["items"] for a in spec["object_types"]["anyOf"] if a.get("type") == "array"]
    assert itens and itens[0]["enum"] == ["user", "group", "computer", "organizationalUnit"]


def test_instrucoes_dizem_a_regra_de_escrita_como_ela_e():
    texto = INSTRUCOES_DO_SERVIDOR.lower()
    for termo in ("palavras inteiras", "abreviacao", "homonimo", "confirme com o usuario"):
        assert termo in texto
