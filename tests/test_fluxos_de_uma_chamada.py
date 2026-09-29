"""Each common operator request is ONE tool call, and its answer is read back.

Measured 2026-09-19 on production: "disable this employee, move her to
_DESATIVADOS, copy her groups and OU to the new hire and create the new hire"
took a model 39 tool calls -- details, group list, OU details and OU contents
separately, then a verification loop -- and still left the account unmoved.
These tests drive the whole server (name resolution included) against a
stateful fake directory and assert on what the directory holds afterwards,
not on what was sent.
"""

import asyncio
import json



from .diretorio_falso import (
    BASE,
    DESATIVADOS,
    FILIAL,
    FIN_FILIAL,
    MATRIZ,
    TI,
)

SID = "S-1-5-21-1000-2000-3000"
SABRINA = f"CN=Sabrina De Moura Lopes Rocha,{FIN_FILIAL}"
JOAO = f"CN=João da Silva,{TI}"
G_FIN = f"CN=Financeiro - Filial,{FILIAL}"
G_MATRIZ = f"CN=Financeiro - Matriz,{MATRIZ}"
G_TI = f"CN=TI Suporte,{TI}"
G_USERS = f"CN=Domain Users,CN=Users,{BASE}"


def chamar(servidor, nome, **args):
    args.setdefault("ad_server", "alfa")
    # The test directory keeps the default "confirm writes" policy on.
    alvo = nome if nome in servidor.tools else \
        servidor.ALIASES_DE_TOOLS.get(nome, (nome,))[0]
    if servidor.tools.get(alvo, {}).get("write"):
        args.setdefault("client_confirmation", "alfa")
    r = asyncio.run(servidor.handle_tools_call({"name": nome, "arguments": args}))
    return json.loads(r["content"][0]["text"])


def _entrada(servidor, dn):
    return servidor.falso._entrada(dn)


def _logins_com(servidor, grupo_dn):
    entrada = _entrada(servidor, grupo_dn)
    membros = entrada.valores("member")
    return sorted(servidor.falso._entrada(m).atributos["sAMAccountName"] for m in membros)


# ------------------------------------------------------------ user details

def test_ficha_traz_grupos_grupo_primario_e_ou(srv):
    r = chamar(srv, "ad_get_user_details_by_username", username="Sabrina Rocha")
    resumo = r["resumo"]
    assert [g["nome"] for g in resumo["grupos"]] == ["Financeiro - Filial", "TI Suporte"]
    assert resumo["grupo_primario"]["nome"] == "Domain Users"
    assert resumo["ou_caminho"] == "_Alfa/Filial/Financeiro"
    assert resumo["ativa"] is True
    assert "memberOf" not in r["attributes"]


def test_ficha_sem_grupos_diz_que_nao_ha_o_que_copiar(srv):
    """The production account had only Domain Users; '0 groups' sent the model
    looking for groups in six other tools."""
    r = chamar(srv, "ad_get_user_details_by_username", username="joao.silva")
    assert r["resumo"]["total_grupos"] == 0
    assert r["resumo"]["grupo_primario"]["nome"] == "Domain Users"
    assert "Nao ha grupos a copiar" in r["resumo"]["nota_grupos"]


# ------------------------------------------------------------ onboarding

def test_admissao_copiando_grupos_e_ou_de_um_colega_pelo_nome(srv):
    r = chamar(srv, "ad_create_user_account", username="marta.souto",
               password="Mudar@12345", first_name="Marta", last_name="Lima Souto",
               copy_from_user="Sabrina Rocha",
               additional_attributes={
                   "Office": "Escritorio Central", "City": "Cidade", "State": "TO",
                   "mobile": "", "Country": "Brasil", "Title": "Assistente Financeiro",
                   "OtherAttributes": {"ipPhone": "NAO POSSUI"}})
    assert r["success"] is True, r
    novo_dn = f"CN=Marta Lima Souto,{FIN_FILIAL}"
    assert r["dn"] == novo_dn and r["ou"] == "_Alfa/Filial/Financeiro"
    assert r["must_change_password"] is True and r["account_enabled"] is True
    assert sorted(r["copied_from"]["groups_joined"]) == ["Financeiro - Filial", "TI Suporte"]
    # What the directory holds, not what was sent:
    criada = _entrada(srv, novo_dn).atributos
    assert criada["physicalDeliveryOfficeName"] == "Escritorio Central"
    assert criada["l"] == "Cidade" and criada["c"] == "BR" and criada["ipPhone"] == "NAO POSSUI"
    assert criada["pwdLastSet"] in (0, "0") and criada["userAccountControl"] == 512
    assert "mobile" not in criada and r["ignorados_vazios"] == ["mobile"]
    assert "marta.souto" in _logins_com(srv, G_FIN) and "marta.souto" in _logins_com(srv, G_TI)


def test_admissao_com_modelo_ambiguo_nao_cria_nada(srv):
    antes = len(srv.falso.entradas)
    r = chamar(srv, "ad_create_user_account", username="novo.joao", password="Mudar@12345",
               first_name="Novo", last_name="Joao", copy_from_user="João")
    assert r.get("sucesso") is False and r["parametro"] == "copy_from_user"
    assert len(srv.falso.entradas) == antes


def test_admissao_com_modelo_sem_grupos_explica(srv):
    r = chamar(srv, "ad_create_user_account", username="novo.ti", password="Mudar@12345",
               first_name="Novo", last_name="Ti", copy_from_user="joao.silva")
    assert r["success"] is True and r["ou"] == "_Alfa/Filial/TI"
    assert r["copied_from"]["groups_joined"] == []
    assert "Domain Users" in r["copied_from"]["nota"]


def test_admissao_respeita_change_password_at_logon_false_do_powershell(srv):
    r = chamar(srv, "ad_create_user_account", username="svc.backup", password="Mudar@12345",
               first_name="Svc", last_name="Backup", ou="TI",
               additional_attributes={"ChangePasswordAtLogon": "$false"})
    assert r["success"] is True and r["must_change_password"] is False


def test_campo_no_topo_nao_some_em_silencio(srv):
    r = chamar(srv, "ad_create_user_account", username="ana.topo", password="Mudar@12345",
               first_name="Ana", last_name="Topo", ou="TI", department="Financeiro",
               Office="Sala 2")
    assert r["success"] is True
    criada = _entrada(srv, f"CN=Ana Topo,{TI}").atributos
    assert criada["department"] == "Financeiro"
    assert criada["physicalDeliveryOfficeName"] == "Sala 2"
    assert sorted(r["parametros_lidos_como_atributos"]) == ["Office", "department"]


# ------------------------------------------------------------ offboarding

def test_desligamento_numa_chamada_desativa_e_move(srv):
    r = chamar(srv, "ad_disable_user_account_access", username="Sabrina Rocha",
               move_to_ou="_DESATIVADOS")
    assert r["success"] is True, r
    novo = f"CN=Sabrina De Moura Lopes Rocha,{DESATIVADOS}"
    assert r["dn"] == novo and r["previous_dn"] == SABRINA and r["account_enabled"] is False
    assert _entrada(srv, novo).atributos["userAccountControl"] == 514
    assert r["groups_kept"] == 2


def test_desligamento_removendo_grupos_devolve_o_que_tirou(srv):
    r = chamar(srv, "ad_disable_user_account_access", username="sabrina.rocha",
               move_to_ou="_DESATIVADOS", remove_from_groups=True)
    assert sorted(g["nome"] for g in r["groups_removed"]) == ["Financeiro - Filial", "TI Suporte"]
    assert r["groups_remaining"] == []
    assert "sabrina.rocha" not in _logins_com(srv, G_FIN)


def test_readmissao_reativa_e_devolve_para_a_ou(srv):
    chamar(srv, "ad_disable_user_account_access", username="sabrina.rocha",
           move_to_ou="_DESATIVADOS")
    r = chamar(srv, "ad_enable_user_account_access", username="sabrina.rocha",
               move_to_ou="Filial/Financeiro")
    assert r["account_enabled"] is True and r["dn"] == SABRINA


def test_desligamento_para_ou_inexistente_nao_desativa_nada(srv):
    r = chamar(srv, "ad_disable_user_account_access", username="sabrina.rocha",
               move_to_ou="Desligados2019")
    assert r.get("sucesso") is False and r["parametro"] == "move_to_ou"
    assert _entrada(srv, SABRINA).atributos["userAccountControl"] == 512


# ------------------------------------------------------ several groups at once

def test_inclusao_em_varios_grupos_numa_chamada(srv):
    r = chamar(srv, "ad_add_member_to_group",
               group_name=["Financeiro - Matriz", "TI Suporte"], member_dn="João Pereira")
    assert r["success"] is True, r
    assert all(x["verified"] for x in r["resultados"])
    assert "joao.pereira" in _logins_com(srv, G_MATRIZ)
    assert "joao.pereira" in _logins_com(srv, G_TI)


def test_lista_com_um_grupo_desconhecido_nao_executa_nenhum(srv):
    r = chamar(srv, "ad_add_member_to_group",
               group_name=["Financeiro - Matriz", "Grupo Que Nao Existe"],
               member_dn="joao.pereira")
    assert r.get("sucesso") is False and r["parametro"] == "group_name[1]"
    assert "joao.pereira" not in _logins_com(srv, G_MATRIZ)


def test_repetir_inclusao_nao_e_falha(srv):
    r = chamar(srv, "ad_add_member_to_group", group_name="TI Suporte", member_dn="sabrina.rocha")
    assert r["success"] is True and r["resultados"][0]["status"] == "ja_era_membro"


# ------------------------------------------------------ group and OU details

def test_grupo_traz_membros_e_expande_aninhados(srv):
    srv.falso.incluir_membro(G_MATRIZ, G_TI)
    direto = chamar(srv, "ad_get_group_details_by_name", group_name="Financeiro - Matriz")
    assert [m["name"] for m in direto["members"]] == ["TI Suporte"]
    tudo = chamar(srv, "ad_get_group_details_by_name", group_name="Financeiro - Matriz",
                  recursive=True)
    nomes = {m["name"]: m for m in tudo["members"]}
    assert nomes["Sabrina De Moura Lopes Rocha"]["via"] == "TI Suporte"


def test_ou_traz_o_conteudo_na_mesma_resposta(srv):
    r = chamar(srv, "ad_get_organizational_unit_details", ou_dn="Filial/Financeiro")
    assert r["type_counts"] == {"computer": 2, "user": 2}
    assert r["computed"]["child_objects_count"] == 4
    so_pessoas = chamar(srv, "ad_get_organizational_unit_details", ou_dn="Filial/Financeiro",
                        object_types=["user"])
    assert {o["login"] for o in so_pessoas["contents"]} == {"sabrina.rocha", "conceicao.alves"}
    assert [o["enabled"] for o in so_pessoas["contents"] if o["login"] == "conceicao.alves"] \
        == [False]


# ------------------------------------------------------------- the catalogue

def test_catalogo_e_uma_busca_e_uma_gestao_por_objeto(srv):
    """38 tools became 10: the old names are not listed anymore."""
    listadas = {t["name"] for t in asyncio.run(srv.handle_tools_list({}))["tools"]}
    assert listadas == {
        "ad_search_directory_servers",
        "ad_search_directory_users", "ad_manage_directory_users",
        "ad_search_directory_groups", "ad_manage_directory_groups",
        "ad_search_directory_computers", "ad_manage_directory_computers",
        "ad_search_organizational_units", "ad_manage_organizational_units",
        "ad_search_security_reports",
    }
    assert not listadas & set(srv.ALIASES_DE_TOOLS)


def test_anotacoes_separam_leitura_de_escrita(srv):
    por_nome = {t["name"]: t["annotations"] for t in
                asyncio.run(srv.handle_tools_list({}))["tools"]}
    for nome, anotacoes in por_nome.items():
        leitura = nome.startswith("ad_search_")
        assert anotacoes["readOnlyHint"] is leitura, nome
        assert anotacoes["destructiveHint"] is not leitura, nome
        assert anotacoes["openWorldHint"] is True and anotacoes["title"]


def test_nome_antigo_ainda_responde_com_aviso(srv):
    r = chamar(srv, "ad_get_user_group_memberships", username="Sabrina Rocha")
    assert "ad_search_directory_users" in r["tool_unificada"]
    assert r["resumo"]["total_grupos"] == 2
    r = chamar(srv, "ad-multi-ad_get_organizational_unit_objects", ou_dn="TI")
    assert "tool_unificada" in r and r["total_count"] >= 1
    # a write through an old name carries the action the alias injected
    r = chamar(srv, "ad_disable_user_account_access", username="sabrina.rocha")
    assert r["success"] is True and "ad_manage_directory_users" in r["tool_unificada"]


def test_nome_antigo_do_catalogo_vira_busca_por_nome(srv):
    r = asyncio.run(srv.handle_tools_call({"name": "ad_check_ad_server_configured",
                                           "arguments": {"server_name": "alfinha"}}))
    corpo = json.loads(r["content"][0]["text"])
    assert corpo["exists"] is True and corpo["ad_server"] == "alfa"


def test_substituicao_na_ordem_errada_nao_poe_a_conta_nova_em_desativados(srv):
    """Offboard first, then copy: the model account's OU is _DESATIVADOS now."""
    chamar(srv, "ad_disable_user_account_access", username="sabrina.rocha",
           move_to_ou="_DESATIVADOS")
    antes = len(srv.falso.entradas)
    r = chamar(srv, "ad_create_user_account", username="marta.souto", password="Mudar@12345",
               first_name="Marta", last_name="Sousa", copy_from_user="sabrina.rocha")
    assert r["success"] is False and "desligados" in r["error"]
    assert len(srv.falso.entradas) == antes
    # With the OU given, the groups still come from the model account.
    r = chamar(srv, "ad_create_user_account", username="marta.souto", password="Mudar@12345",
               first_name="Marta", last_name="Sousa", copy_from_user="sabrina.rocha",
               ou="Filial/Financeiro")
    assert r["success"] is True and r["ou"] == "_Alfa/Filial/Financeiro"
    assert sorted(r["copied_from"]["groups_joined"]) == ["Financeiro - Filial", "TI Suporte"]
