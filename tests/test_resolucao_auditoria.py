"""Findings of the independent audit of the resolver (2026-09-18), one test each.

Every case below made a WRITE tool act on an object other than the one the
operator typed, or reported a refusal as "nothing found". Several were measured
live on the production directories (read-only): a dotted login with one typo
resolved "exato" to a different account in 29 cases, and 200 of 200 e-mails
from another customer's domain resolved to this customer's account.

Write policy these tests hold (decided by the owner): a write runs only on an
exact unique identifier, or when exactly one object contains every typed word
as a whole word. Prefixes, initials, fragments, typos and ambiguity never write.
"""

import asyncio
import json

import pytest

from active_directory_mcp.core.resolver import resolver_argumentos
from active_directory_mcp.server_fastapi import ActiveDirectoryMCPFastAPI

from .diretorio_falso import (
    BASE,
    DESATIVADOS,
    FILIAL,
    FIN_FILIAL,
    RAIZ,
    TI,
    DiretorioFalso,
    computador,
    diretorio_padrao,
    grupo,
    unidade,
    usuario,
)

USERS = f"CN=Users,{BASE}"


def escrever(ldap, tool, **args):
    return resolver_argumentos(tool, args, ldap, BASE, escrita=True)


def ler(ldap, tool, **args):
    return resolver_argumentos(tool, args, ldap, BASE, escrita=False)


def resolvido(resultado, parametro):
    novos, recusa, _ = resultado
    return None if recusa else novos[parametro]


# ------------------------------------------------ CRITICAL: identificador com ponto

def test_ponto_nao_corta_o_nome_e_move_a_ou_inteira():
    # "TI.Suporte" meant the group "TI Suporte"; the split made it the OU "TI".
    r = escrever(diretorio_padrao(), "ad_move_organizational_unit_parent",
                 object_name="TI.Suporte", new_parent_dn="_DESATIVADOS")
    assert resolvido(r, "object_name") != TI


def test_host_com_sufixo_desconhecido_nao_vira_o_computador():
    r = escrever(diretorio_padrao(), "ad_add_member_to_group",
                 group_name="TI Suporte", member_dn="fin-pc01.antigo")
    assert resolvido(r, "member_dn") is None


def test_login_com_erro_de_digitacao_nao_vira_o_primeiro_pedaco():
    falso = diretorio_padrao()
    falso.entradas.append(type(falso.entradas[0])(*usuario("Joao Batista", "joao", USERS)))
    # The auditor's case: member_dn (kind "membro") is where the dot was split.
    r = escrever(falso, "ad_add_member_to_group", group_name="TI Suporte",
                 member_dn="joao.silvaa")
    assert resolvido(r, "member_dn") is None


def test_dominio_barra_login_nao_fica_ambiguo_com_login_curto():
    falso = diretorio_padrao()
    falso.entradas.append(type(falso.entradas[0])(*usuario("Joao Batista", "joao", USERS)))
    r = escrever(falso, "ad_add_member_to_group", group_name="TI Suporte",
                 member_dn="ALFA\\joao.silva")
    assert resolvido(r, "member_dn") == f"CN=João da Silva,{TI}", r[1]


def test_fqdn_do_proprio_dominio_continua_resolvendo():
    r = escrever(diretorio_padrao(), "ad_disable_computer_account_trust",
                 computer_name="fin-pc01.alfa.local")
    assert resolvido(r, "computer_name") == "FIN-PC01$"


# --------------------------------------------------- HIGH: prefixo nao e palavra

def test_prefixo_nao_escreve():
    novos, recusa, _ = escrever(diretorio_padrao(), "ad_delete_user_account_permanently",
                                username="Mari Souza")
    assert novos is None and recusa["erro"] == "CORRESPONDENCIA_PARCIAL_EM_ESCRITA"


def test_prefixo_em_leitura_resolve_com_aviso():
    novos, recusa, ident = ler(diretorio_padrao(), "ad_get_user_details_by_username",
                               username="Mari Souza")
    assert recusa is None and novos["username"] == "mariana.souza"
    assert ident[0]["nivel"] == "prefixo" and ident[0].get("aviso")


# ------------------------------------------- HIGH: nenhuma palavra digitada some

@pytest.mark.parametrize("entrada", ["Z Pereira", "Joao Silva 2", "J Pereira"])
def test_palavra_curta_nao_e_descartada_na_escrita(entrada):
    r = escrever(diretorio_padrao(), "ad_delete_user_account_permanently", username=entrada)
    assert resolvido(r, "username") is None, (entrada, r[0])


def test_numero_diferente_nao_vira_outro_computador():
    loja = unidade("Loja", BASE)
    falso = DiretorioFalso(BASE, [loja, computador("LOJA-PC-1", loja[0])])
    for entrada in ("LOJA-PC-3", "LOJA PC 7"):
        r = escrever(falso, "ad_delete_computer_account_permanently", computer_name=entrada)
        assert resolvido(r, "computer_name") is None, entrada


def test_inicial_em_leitura_resolve_com_aviso():
    novos, recusa, ident = ler(diretorio_padrao(), "ad_get_user_details_by_username",
                               username="J Pereira")
    assert recusa is None and novos["username"] == "joao.pereira"
    assert ident[0].get("aviso")


# ------------------------------------------------ HIGH: dominio digitado conta

@pytest.mark.parametrize("entrada", ["joao.pereira@beta.com.br", "BETA\\joao.pereira"])
def test_identificador_de_outro_dominio_e_recusado(entrada):
    for funcao in (escrever, ler):
        novos, recusa, _ = funcao(diretorio_padrao(), "ad_disable_user_account_access",
                                  username=entrada)
        assert novos is None and recusa["erro"] == "OBJETO_FORA_DO_DOMINIO", (entrada, recusa)


@pytest.mark.parametrize("entrada", ["pereira@alfa.com", "ALFA\\j.pereira"])
def test_escrita_nao_cai_do_endereco_para_o_nome(entrada):
    r = escrever(diretorio_padrao(), "ad_disable_user_account_access", username=entrada)
    assert resolvido(r, "username") is None


def test_computador_com_dominio_de_outro_cliente_nao_resolve():
    r = escrever(diretorio_padrao(), "ad_delete_computer_account_permanently",
                 computer_name="FIN-PC01.beta.local")
    assert resolvido(r, "computer_name") is None


# ------------------------------------------ HIGH: caminho de OU com fragmento

@pytest.mark.parametrize("entrada", ["Filial/Fin", "Filial/anceir"])
def test_fragmento_no_caminho_nao_escreve(entrada):
    r = escrever(diretorio_padrao(), "ad_delete_organizational_unit_forced",
                 ou_dn=entrada, force=True)
    assert resolvido(r, "ou_dn") is None, entrada


def test_caminho_nao_contiguo_nao_escreve():
    antigo = f"OU=Antigo,{FILIAL}"
    falso = DiretorioFalso(BASE, [unidade("_Alfa", BASE), unidade("Filial", RAIZ),
                                  unidade("Antigo", FILIAL), unidade("Financeiro", antigo)])
    r = escrever(falso, "ad_delete_organizational_unit_forced",
                 ou_dn="Filial/Financeiro", force=True)
    assert resolvido(r, "ou_dn") is None
    _, recusa, ident = ler(falso, "ad_get_organizational_unit_details",
                           ou_dn="Filial/Financeiro")
    assert recusa is None and ident[0].get("aviso")


def test_caminho_contiguo_continua_escrevendo():
    r = escrever(diretorio_padrao(), "ad_delete_organizational_unit_forced",
                 ou_dn="Filial/Financeiro", force=True)
    assert resolvido(r, "ou_dn") == FIN_FILIAL


# ----------------------------------------- HIGH: tipos diferentes, mesmo nome

def test_grupo_e_ou_com_o_mesmo_nome_sao_ambiguos():
    falso = diretorio_padrao()
    falso.entradas.append(type(falso.entradas[0])(*grupo("TI", "ti", FILIAL)))
    novos, recusa, _ = escrever(falso, "ad_move_organizational_unit_parent",
                                object_name="TI", new_parent_dn="_DESATIVADOS")
    assert novos is None and recusa["erro"] == "IDENTIFICACAO_AMBIGUA"
    assert {c["tipo"] for c in recusa["candidatos"]} == {"grupo", "ou"}


def test_object_type_desfaz_a_ambiguidade():
    falso = diretorio_padrao()
    falso.entradas.append(type(falso.entradas[0])(*grupo("TI", "ti", FILIAL)))
    r = escrever(falso, "ad_move_organizational_unit_parent", object_name="TI",
                 object_type="organizational_unit", new_parent_dn="_DESATIVADOS")
    assert resolvido(r, "object_name") == TI


def test_homonimo_de_nome_exato_nao_escreve_mas_le():
    falso = DiretorioFalso(BASE, [usuario("Tamara Lima", "tamaralima", USERS),
                                  usuario("Tamara Lima 1", "tamaralima1", USERS)])
    novos, recusa, _ = escrever(falso, "ad_disable_user_account_access", username="Tamara Lima")
    assert novos is None and recusa["erro"] == "IDENTIFICACAO_AMBIGUA"
    assert recusa["candidatos"][0]["login"] == "tamaralima"
    novos, recusa, ident = ler(falso, "ad_get_user_details_by_username", username="Tamara Lima")
    assert novos["username"] == "tamaralima" and ident[0].get("aviso")


def test_objeto_por_caminho_de_ou():
    r = escrever(diretorio_padrao(), "ad_move_organizational_unit_parent",
                 object_name="Filial/TI", new_parent_dn="_DESATIVADOS")
    assert resolvido(r, "object_name") == TI


# ------------------------------------------------------------ entradas invalidas

def test_object_type_invalido_e_recusado():
    novos, recusa, _ = escrever(diretorio_padrao(), "ad_move_organizational_unit_parent",
                                object_name="TI", object_type="impressora",
                                new_parent_dn="_DESATIVADOS")
    assert novos is None and recusa["erro"] == "PARAMETRO_INVALIDO"
    assert "user" in recusa["mensagem"]


def test_object_type_em_portugues_e_aceito():
    r = escrever(diretorio_padrao(), "ad_move_organizational_unit_parent",
                 object_name="TI Suporte", object_type="Grupo", new_parent_dn="_DESATIVADOS")
    assert resolvido(r, "object_name") == f"CN=TI Suporte,{TI}"


def test_filtro_sem_palavras_e_recusado():
    novos, recusa, _ = ler(diretorio_padrao(), "ad_search_directory_users",
                           filter_criteria="***")
    assert novos is None and recusa["erro"] == "PARAMETRO_INVALIDO"


def test_recusa_parcial_manda_confirmar_com_o_usuario():
    _, recusa, _ = escrever(diretorio_padrao(), "ad_disable_user_account_access",
                            username="abrin")
    assert "confirme com o usuario" in recusa["mensagem"].lower()


# ------------------------------------------------------ servidor: todos e mover

def _servidor(tmp_path, falso):
    bloco = {
        "label": "Alfa", "enabled": True,
        "active_directory": {"server": "ldaps://10.0.0.1:636", "domain": "alfa.local",
                             "base_dn": BASE, "bind_dn": f"CN=svc,{BASE}", "password": "x"},
        "organizational_units": {"users_ou": USERS, "groups_ou": USERS,
                                 "computers_ou": USERS, "service_accounts_ou": USERS},
        "client": {"security": {"require_confirmation_for_writes": False}},
    }
    caminho = tmp_path / "s.json"
    caminho.write_text(json.dumps({"version": 1, "servers": {"alfa": bloco}}), encoding="utf-8")
    srv = ActiveDirectoryMCPFastAPI(port=0, servers_path=str(caminho), mode="multi")
    bundle, _ = srv.pool.resolve_or_error("alfa")
    bundle.ldap_manager = falso
    for nome in ("user_tools", "group_tools", "computer_tools", "ou_tools", "security_tools"):
        getattr(bundle, nome).ldap = falso
    return srv


def chamar(srv, nome, **args):
    r = asyncio.run(srv.handle_tools_call({"name": nome, "arguments": args}))
    return json.loads(r["content"][0]["text"])


def test_todos_devolve_a_recusa_de_entrada(tmp_path):
    srv = _servidor(tmp_path, diretorio_padrao())
    r = chamar(srv, "ad_search_directory_users", filter_criteria="(&(cn=a)", ad_server="todos")
    assert r.get("erro") == "FILTRO_LDAP_INVALIDO", r


def test_mover_por_ou_dn_legado_so_move_ou(tmp_path):
    falso = diretorio_padrao()
    srv = _servidor(tmp_path, falso)
    r = chamar(srv, "ad_move_organizational_unit_parent", ad_server="alfa",
               ou_dn="Users", new_parent_dn="_DESATIVADOS")
    assert falso.movimentos == [], r


def test_mover_nao_confunde_ou_com_espaco(tmp_path):
    ab, a_b = unidade("AB", BASE), unidade("A B", BASE)
    pessoa = usuario("Rita Moura", "rita.moura", a_b[0])
    falso = DiretorioFalso(BASE, [ab, a_b, pessoa])
    srv = _servidor(tmp_path, falso)
    r = chamar(srv, "ad_move_organizational_unit_parent", ad_server="alfa",
               object_name="rita.moura", new_parent_dn=ab[0])
    assert falso.movimentos == [(pessoa[0], ab[0])], r
    assert r.get("changed") is True


def test_dn_de_outro_dominio_recusado_com_o_codigo_certo(tmp_path):
    srv = _servidor(tmp_path, diretorio_padrao())
    r = chamar(srv, "ad_add_member_to_group", ad_server="alfa", group_name="TI Suporte",
               member_dn="CN=Rita,OU=X,DC=outro,DC=local")
    assert r["erro"] == "OBJETO_FORA_DO_DOMINIO"


def test_desativar_move_para_desativados_fluxo_completo(tmp_path):
    falso = diretorio_padrao()
    srv = _servidor(tmp_path, falso)
    r = chamar(srv, "ad_move_organizational_unit_parent", ad_server="alfa",
               object_name="Sabrina Rocha", new_parent_dn="_DESATIVADOS")
    assert r["success"] is True and r["new_dn"].endswith(DESATIVADOS), r
