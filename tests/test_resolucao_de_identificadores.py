"""The server, not the model, turns what the operator typed into an AD object.

Measured on the production instance before the resolver existed: an operator
asked to offboard an employee by full name. The model called

    ad_get_user_details_by_username(username="<nome completo>", ad_server="todos")

and got "found in 0 of 8 servers" -- every tool looked up sAMAccountName and
nothing else. The account existed: the full name was its CN, while displayName
read "<Nome Sobrenome> - Administrativo Financeiro". Its fallback,
ad_list_users_with_filters(filter_criteria="<nome completo>"), answered
"malformed filter". The model gave up and asked the operator for the login.

The directory below reproduces that shape with invented names.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from active_directory_mcp.server_fastapi import ActiveDirectoryMCPFastAPI

from .diretorio_falso import (
    BASE,
    DESATIVADOS,
    FIN_FILIAL,
    FIN_MATRIZ,
    MATRIZ,
    TI,
    diretorio_padrao,
)

SABRINA_DN = f"CN=Sabrina De Moura Lopes Rocha,{FIN_FILIAL}"
_TOOLSETS = ("user_tools", "group_tools", "computer_tools", "ou_tools", "security_tools")


def _config_multi(tmp_path):
    bloco = {
        "label": "Alfa", "aliases": ["alfinha"], "enabled": True,
        "active_directory": {
            "server": "ldaps://10.0.0.1:636", "domain": "alfa.local",
            "base_dn": BASE, "bind_dn": f"CN=svc,{BASE}",
            "password": "x", "timeout": 5},
        "organizational_units": {
            "users_ou": f"CN=Users,{BASE}", "groups_ou": f"CN=Users,{BASE}",
            "computers_ou": f"CN=Users,{BASE}", "service_accounts_ou": f"CN=Users,{BASE}"},
    }
    caminho = tmp_path / "s.json"
    caminho.write_text(json.dumps({"version": 1, "servers": {"alfa": bloco}}), encoding="utf-8")
    return str(caminho)


@pytest.fixture
def servidor(tmp_path):
    srv = ActiveDirectoryMCPFastAPI(port=0, servers_path=_config_multi(tmp_path), mode="multi")
    bundle, erro = srv.pool.resolve_or_error("alfa")
    assert erro is None, erro
    falso = diretorio_padrao()
    bundle.ldap_manager = falso
    for nome in _TOOLSETS:
        getattr(bundle, nome).ldap = falso
    srv.falso = falso
    return srv


def chamar(srv, nome, **args):
    args.setdefault("ad_server", "alfa")
    alvo = nome if nome in srv.tools else srv.ALIASES_DE_TOOLS.get(nome, (nome,))[0]
    if srv.tools.get(alvo, {}).get("write"):
        args.setdefault("client_confirmation", "alfa")
    r = asyncio.run(srv.handle_tools_call({"name": nome, "arguments": args}))
    return json.loads(r["content"][0]["text"])


def espiar(srv, tool_name):
    """Replace the handler with a spy: what reaches it is the resolved call.

    A tool name that was merged into another (the 2026-09-19 catalogue) is
    followed to its replacement, so a test written against the old name spies
    on the tool that actually answers it.
    """
    visto = {}

    def spy(params):
        visto.update(params)
        return {"ok": True}

    alvo = tool_name if tool_name in srv.tools else \
        srv.ALIASES_DE_TOOLS[tool_name][0]
    srv.tools[alvo]["handler"] = spy
    return visto


# ------------------------------------------------ o caso de producao, reproduzido

def test_nome_completo_que_e_o_cn_chega_ao_handler_como_login(servidor):
    visto = espiar(servidor, "ad_get_user_details_by_username")
    r = chamar(servidor, "ad_get_user_details_by_username",
               username="Sabrina De Moura Lopes Rocha")
    assert visto.get("username") == "sabrina.rocha", r
    ident = r["identificacao"][0]
    assert ident["informado"] == "Sabrina De Moura Lopes Rocha"
    assert ident["resolvido_para"] == "sabrina.rocha"
    assert ident["dn"] == SABRINA_DN


def test_nome_completo_em_todos_os_servidores_encontra(servidor):
    # Real handler, no spy: a spy answers "ok" everywhere and would pass
    # without anything having been found.
    r = chamar(servidor, "ad_get_user_details_by_username",
               username="Sabrina De Moura Lopes Rocha", ad_server="todos")
    assert r["encontrado_em"] == ["alfa"], r
    detalhe = json.dumps(r["resultados_por_servidor"]["alfa"], ensure_ascii=False)
    assert "sabrina.rocha" in detalhe


@pytest.mark.parametrize("entrada", [
    "Sabrina Rocha",                 # nome de exibicao sem o sufixo
    "rocha sabrina",                 # ordem trocada
    "SABRINA MOURA",                 # maiusculas, sobrenome do meio
    "sabrina.moura",                 # login chutado pelo modelo
    "sabrina.rocha@alfa.com",        # e-mail
    "ALFA\\sabrina.rocha",           # DOMINIO\usuario
    SABRINA_DN,                      # DN completo
    "  sabrina.rocha  ",             # espacos
])
def test_formas_de_identificar_a_mesma_pessoa(servidor, entrada):
    visto = espiar(servidor, "ad_get_user_details_by_username")
    r = chamar(servidor, "ad_get_user_details_by_username", username=entrada)
    assert visto.get("username") == "sabrina.rocha", r


@pytest.mark.parametrize("entrada,login", [
    ("Conceicao Alves", "conceicao.alves"),   # sem acento contra nome com acento
    ("joao silva", "joao.silva"),
    ("JOÃO PEREIRA", "joao.pereira"),
])
def test_acento_e_maiuscula_nao_importam(servidor, entrada, login):
    visto = espiar(servidor, "ad_get_user_details_by_username")
    chamar(servidor, "ad_get_user_details_by_username", username=entrada)
    assert visto.get("username") == login


# ------------------------------------------------------- ambiguidade e ausencia

def test_nome_ambiguo_lista_candidatos_e_nao_executa(servidor):
    visto = espiar(servidor, "ad_get_user_details_by_username")
    r = chamar(servidor, "ad_get_user_details_by_username", username="João")
    assert not visto, "o handler nao pode rodar com identificacao ambigua"
    assert r["erro"] == "IDENTIFICACAO_AMBIGUA"
    logins = {c["login"] for c in r["candidatos"]}
    assert logins == {"joao.silva", "joao.pereira"}
    assert all("ou" in c and "ativo" in c for c in r["candidatos"])


def test_palavra_inteira_vence_trecho(servidor):
    # "Ana" e palavra inteira em "Ana Clara Mendes" e so trecho de "Mariana".
    visto = espiar(servidor, "ad_get_user_details_by_username")
    chamar(servidor, "ad_get_user_details_by_username", username="Ana")
    assert visto.get("username") == "ana.mendes"


def test_nao_encontrado_diz_onde_procurou(servidor):
    visto = espiar(servidor, "ad_get_user_details_by_username")
    r = chamar(servidor, "ad_get_user_details_by_username", username="Fulano Beltrano")
    assert not visto
    assert r["erro"] == "OBJETO_NAO_ENCONTRADO"
    for campo in ("login", "e-mail", "nome"):
        assert campo in r["mensagem"]


def test_erro_de_digitacao_em_leitura_resolve_com_aviso(servidor):
    visto = espiar(servidor, "ad_get_user_details_by_username")
    r = chamar(servidor, "ad_get_user_details_by_username", username="Sabirna Rocha")
    assert visto.get("username") == "sabrina.rocha"
    assert r["identificacao"][0]["nivel"] == "aproximado"
    assert r["identificacao"][0].get("aviso")


def test_nao_encontrado_em_todos_mostra_parecidos(servidor):
    espiar(servidor, "ad_get_user_details_by_username")
    r = chamar(servidor, "ad_get_user_details_by_username",
               username="Fulano Rocha", ad_server="todos")
    assert r["encontrado_em"] == []
    parecidos = r["parecidos_por_servidor"]["alfa"]
    assert any(p["login"] == "sabrina.rocha" for p in parecidos)


# ----------------------------------------------------- escrita: todas as palavras

def test_escrita_com_todas_as_palavras_executa_e_diz_quem(servidor):
    visto = espiar(servidor, "ad_disable_user_account_access")
    r = chamar(servidor, "ad_disable_user_account_access", username="Sabrina Rocha")
    assert visto.get("username") == "sabrina.rocha", r
    assert r["identificacao"][0]["resolvido_para"] == "sabrina.rocha"


def test_escrita_ambigua_nao_executa(servidor):
    visto = espiar(servidor, "ad_disable_user_account_access")
    r = chamar(servidor, "ad_disable_user_account_access", username="João")
    assert not visto
    assert r["erro"] == "IDENTIFICACAO_AMBIGUA"


@pytest.mark.parametrize("entrada", ["abrin", "Sabirna Rocha"])
def test_escrita_por_trecho_ou_aproximacao_nao_executa(servidor, entrada):
    visto = espiar(servidor, "ad_disable_user_account_access")
    r = chamar(servidor, "ad_disable_user_account_access", username=entrada)
    assert not visto, "escrita nunca executa por trecho ou por erro de digitacao"
    assert r["erro"] == "CORRESPONDENCIA_PARCIAL_EM_ESCRITA"
    assert r["candidatos"][0]["login"] == "sabrina.rocha"


def test_escrita_com_dn_de_outro_dominio_e_recusada(servidor):
    visto = espiar(servidor, "ad_add_member_to_group")
    r = chamar(servidor, "ad_add_member_to_group", group_name="TI Suporte",
               member_dn="CN=Sabrina De Moura Lopes Rocha,OU=X,DC=outro,DC=local")
    assert not visto
    assert r["erro"] == "OBJETO_FORA_DO_DOMINIO"


# ------------------------------------------------ grupos, computadores e OUs

@pytest.mark.parametrize("entrada", ["Financeiro - Filial", "financeiro filial", "fin-filial"])
def test_grupo_por_nome_ou_parte(servidor, entrada):
    visto = espiar(servidor, "ad_get_group_details_by_name")
    chamar(servidor, "ad_get_group_details_by_name", group_name=entrada)
    assert visto.get("group_name") == "fin-filial"


@pytest.mark.parametrize("entrada", ["fin-pc01", "FIN-PC01$", "fin-pc01.alfa.local", "pc01"])
def test_computador_por_nome_host_ou_parte(servidor, entrada):
    visto = espiar(servidor, "ad_get_computer_details_by_name")
    chamar(servidor, "ad_get_computer_details_by_name", computer_name=entrada)
    assert visto.get("computer_name") == "FIN-PC01$"


@pytest.mark.parametrize("entrada,dn", [
    ("_DESATIVADOS", DESATIVADOS),
    ("desativados", DESATIVADOS),
    ("Filial/Financeiro", FIN_FILIAL),
    ("_Alfa > Matriz > Financeiro", FIN_MATRIZ),
    ("OU=TI,OU=Filial,OU=_Alfa", TI),
])
def test_ou_por_nome_caminho_ou_dn_parcial(servidor, entrada, dn):
    visto = espiar(servidor, "ad_get_organizational_unit_details")
    chamar(servidor, "ad_get_organizational_unit_details", ou_dn=entrada)
    assert visto.get("ou_dn") == dn


def test_ou_com_nome_repetido_e_ambigua(servidor):
    visto = espiar(servidor, "ad_get_organizational_unit_details")
    r = chamar(servidor, "ad_get_organizational_unit_details", ou_dn="Financeiro")
    assert not visto
    assert r["erro"] == "IDENTIFICACAO_AMBIGUA"
    assert {c["dn"] for c in r["candidatos"]} == {FIN_FILIAL, FIN_MATRIZ}


def test_membro_e_grupo_por_nome(servidor):
    visto = espiar(servidor, "ad_add_member_to_group")
    r = chamar(servidor, "ad_add_member_to_group",
               group_name="Financeiro - Filial", member_dn="Sabrina Rocha")
    # the old name is an alias of ad_manage_directory_groups(action=add_members),
    # where the member parameter is called `members`
    assert visto.get("group_name") == "fin-filial", r
    assert visto.get("members") == SABRINA_DN
    assert visto.get("action") == "add_members"


def test_atributo_manager_por_nome_vira_dn(servidor):
    visto = espiar(servidor, "ad_modify_user_attributes")
    chamar(servidor, "ad_modify_user_attributes", username="Sabrina Rocha",
           attributes={"title": "Analista", "manager": "João da Silva"})
    assert visto["attributes"]["manager"] == f"CN=João da Silva,{TI}"
    assert visto["attributes"]["title"] == "Analista"


# ----------------------------------------------------- criacao: nome novo e livre

def test_criacao_nao_resolve_o_nome_novo_mas_resolve_a_ou(servidor):
    visto = espiar(servidor, "ad_create_user_account")
    r = chamar(servidor, "ad_create_user_account", username="maria.sousa",
               password="Temporaria#2026", first_name="Maria", last_name="Sousa",
               ou="_DESATIVADOS")
    assert visto.get("username") == "maria.sousa", r
    assert visto.get("ou") == DESATIVADOS


# ------------------------------------------------------ filtro de listagem

def test_texto_livre_no_filtro_vira_busca_por_nome(servidor):
    visto = espiar(servidor, "ad_list_users_with_filters")
    r = chamar(servidor, "ad_list_users_with_filters",
               filter_criteria="Sabrina De Moura Lopes Rocha")
    assert "filter_criteria" in visto, r
    base = "(&(objectCategory=person)(objectClass=user))"
    filtro = f"(&{base}{visto['filter_criteria']})"
    achados = servidor.falso.search(BASE, filtro, ["sAMAccountName"])
    assert [a["attributes"]["sAMAccountName"] for a in achados] == ["sabrina.rocha"]


def test_filtro_ldap_malformado_explica_e_nao_executa(servidor):
    visto = espiar(servidor, "ad_list_users_with_filters")
    r = chamar(servidor, "ad_list_users_with_filters", filter_criteria="(&(cn=a)")
    assert not visto
    assert r["erro"] == "FILTRO_LDAP_INVALIDO"
    assert "(" in r["mensagem"]


def test_filtro_ldap_valido_passa_intacto(servidor):
    visto = espiar(servidor, "ad_list_users_with_filters")
    chamar(servidor, "ad_list_users_with_filters", filter_criteria="(department=TI)")
    assert visto["filter_criteria"] == "(department=TI)"


# ------------------------------------------ mover objeto (tool de OU estendida)

def test_mover_usuario_por_nome_para_ou_por_nome(servidor):
    # This fixture keeps the default require_confirmation_for_writes=true, so
    # the confirmation still has to pass -- it is orthogonal to name resolution.
    r = chamar(servidor, "ad_move_organizational_unit_parent",
               object_name="Sabrina Rocha", new_parent_dn="_DESATIVADOS",
               client_confirmation="alfa")
    assert servidor.falso.movimentos == [(SABRINA_DN, DESATIVADOS)], r
    assert r["success"] is True, r
    assert r["new_dn"] == f"CN=Sabrina De Moura Lopes Rocha,{DESATIVADOS}"
    assert r["verified"] is True


def test_mover_ou_devolve_o_dn_novo_certo(servidor):
    # Before: new_dn was built from name[0] -- on a string that is its FIRST
    # LETTER, so moving "TI" reported "OU=T,...".
    r = chamar(servidor, "ad_move_organizational_unit_parent",
               ou_dn=TI, new_parent_dn=MATRIZ, client_confirmation="alfa")
    assert r["success"] is True, r
    assert r["new_dn"] == f"OU=TI,{MATRIZ}"


def test_mover_sem_objeto_explica(servidor):
    r = chamar(servidor, "ad_move_organizational_unit_parent", new_parent_dn="_DESATIVADOS")
    assert r["sucesso"] is False
    assert "object_name" in r["mensagem"]


# --------------------------------------------------------------- modo single

def test_modo_single_tambem_resolve():
    falso = diretorio_padrao()
    srv = ActiveDirectoryMCPFastAPI.__new__(ActiveDirectoryMCPFastAPI)
    srv.multi, srv.pool, srv.security_manager = False, None, None
    srv.logger = __import__("logging").getLogger("teste")
    srv.config = SimpleNamespace(
        active_directory=SimpleNamespace(base_dn=BASE, domain="alfa.local"))
    srv.ldap_manager = falso
    for nome in _TOOLSETS:
        setattr(srv, nome, None)
    srv._build_tool_registry()
    visto = espiar(srv, "ad_get_user_details_by_username")
    r = asyncio.run(srv.handle_tools_call({
        "name": "ad_get_user_details_by_username",
        "arguments": {"username": "Sabrina De Moura Lopes Rocha"}}))
    assert visto.get("username") == "sabrina.rocha", r


# ------------------------------------------ medido na bancada contra os 8 ADs

def test_nome_exato_vence_mas_avisa_quem_tem_as_mesmas_palavras():
    from active_directory_mcp.core.resolver import ResolvedorAD

    from .diretorio_falso import DiretorioFalso, usuario
    ou = f"CN=Users,{BASE}"
    falso = DiretorioFalso(BASE, [usuario("Tamara Lima", "tamaralima", ou),
                                  usuario("Tamara Lima 1", "tamaralima1", ou)])
    # Read: the exact name wins and the twin is shown. The write side of this
    # case is refused as ambiguous -- see test_resolucao_auditoria.py.
    res = ResolvedorAD(falso, BASE).resolver("usuario", "Tamara Lima", escrita=False)
    assert res.situacao == "resolvido" and res.valor == "tamaralima"
    assert [o["login"] for o in res.outros] == ["tamaralima1"]
    assert res.aviso


def test_upn_desempata_quando_o_mail_se_repete():
    from active_directory_mcp.core.resolver import ResolvedorAD

    from .diretorio_falso import DiretorioFalso, usuario
    ou = f"CN=Users,{BASE}"
    dono_dn, dono = usuario("Caixa Financeiro", "financeiro", ou)
    outro_dn, outro = usuario("Caixa Financeiro Antiga", "financeiro.old", ou)
    outro["mail"] = dono["mail"]           # mail duplicado, UPN unico
    falso = DiretorioFalso(BASE, [(dono_dn, dono), (outro_dn, outro)])
    # Read: the UPN owner, with the other holder shown.
    res = ResolvedorAD(falso, BASE).resolver("usuario", dono["userPrincipalName"], escrita=False)
    assert res.situacao == "resolvido" and res.valor == "financeiro"
    assert [o["login"] for o in res.outros] == ["financeiro.old"] and res.aviso
    # Write: ambiguous (owner's decision, 2026-09-18) -- a shared mailbox address
    # must not disable the mailbox when the operator meant the person, or back.
    res = ResolvedorAD(falso, BASE).resolver("usuario", dono["userPrincipalName"], escrita=True)
    assert res.situacao == "ambiguo"
    assert [c["login"] for c in res.candidatos] == ["financeiro", "financeiro.old"]
