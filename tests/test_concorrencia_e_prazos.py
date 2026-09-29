"""One slow directory must not slow, block or mislabel anything else.

Measured on production, 2026-09-19: two customers' directories were behind VPNs
that were down. Each call to them cost 32 s (3 connect attempts of ~10 s plus
2 x 1 s). The server ran handlers on the event loop under one global lock, so:

  * ad_server="todos" walked the eight directories in sequence -- 2.7 s to find
    the user, then 32 s + 32 s on the two dead ones, past the client's 30 s;
  * every other call, ad_list_ad_servers included, queued behind it;
  * a directory that could not be reached was reported as "sem resultado".
"""

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from ldap3.core.exceptions import LDAPException, LDAPSocketOpenError

from active_directory_mcp.core import ldap_manager as lm
from active_directory_mcp.server_fastapi import ActiveDirectoryMCPFastAPI
from active_directory_mcp.tools.computer import ComputerTools
from active_directory_mcp.tools.group import GroupTools
from active_directory_mcp.tools.organizational_unit import OrganizationalUnitTools
from active_directory_mcp.tools.security import SecurityTools
from active_directory_mcp.tools.user import UserTools

from .diretorio_falso import BASE, DiretorioFalso, diretorio_padrao, usuario

_TOOLSETS = ("user_tools", "group_tools", "computer_tools", "ou_tools", "security_tools")


class DiretorioLento(DiretorioFalso):
    """A directory that answers after `atraso` seconds, or fails like a dead VPN."""

    def __init__(self, base, entradas, atraso=0.0, falha=None):
        super().__init__(base, entradas)
        self.atraso = atraso
        self.falha = falha

    def search(self, *args, **kwargs):
        if self.atraso:
            time.sleep(self.atraso)
        if self.falha:
            raise LDAPException(self.falha)
        return super().search(*args, **kwargs)


def _bloco(nome):
    base = f"DC={nome},DC=local"
    return base, {
        "label": nome.title(), "enabled": True,
        "active_directory": {"server": "ldaps://10.0.0.1:636", "domain": f"{nome}.local",
                             "base_dn": base, "bind_dn": f"CN=svc,{base}", "password": "x"},
        "organizational_units": {"users_ou": f"CN=Users,{base}",
                                 "groups_ou": f"CN=Users,{base}",
                                 "computers_ou": f"CN=Users,{base}",
                                 "service_accounts_ou": f"CN=Users,{base}"},
        "client": {"security": {"require_confirmation_for_writes": False}},
    }


def servidor_com(tmp_path, diretorios):
    """diretorios: {nome: callable(base) -> DiretorioFalso}"""
    blocos = {nome: _bloco(nome)[1] for nome in diretorios}
    caminho = tmp_path / "s.json"
    caminho.write_text(json.dumps({"version": 1, "servers": blocos}), encoding="utf-8")
    srv = ActiveDirectoryMCPFastAPI(port=0, servers_path=str(caminho), mode="multi")
    for nome, fabrica in diretorios.items():
        bundle, erro = srv.pool.resolve_or_error(nome)
        assert erro is None, erro
        falso = fabrica(_bloco(nome)[0])
        bundle.ldap_manager = falso
        for conjunto in _TOOLSETS:
            getattr(bundle, conjunto).ldap = falso
    return srv


def pessoas(base, atraso=0.0, falha=None):
    return DiretorioLento(base, [
        usuario("Sabrina De Moura Lopes Rocha", "sabrina.rocha", f"CN=Users,{base}",
                exibicao="Sabrina Rocha - Financeiro"),
    ], atraso=atraso, falha=falha)


async def chamar(srv, nome, **args):
    r = await srv.handle_tools_call({"name": nome, "arguments": args})
    return json.loads(r["content"][0]["text"])


# ------------------------------------------------------- o processo nao congela

def test_listar_servidores_nao_espera_ad_lento(tmp_path):
    srv = servidor_com(tmp_path, {"alfa": lambda b: pessoas(b, atraso=1.5),
                                  "beta": pessoas})

    async def cenario():
        inicio = time.monotonic()
        lenta = asyncio.create_task(chamar(srv, "ad_get_user_details_by_username",
                                           ad_server="alfa", username="Sabrina Rocha"))
        await asyncio.sleep(0.1)
        lista = await chamar(srv, "ad_list_ad_servers")
        tempo_lista = time.monotonic() - inicio
        await lenta
        return lista, tempo_lista

    lista, tempo_lista = asyncio.run(cenario())
    assert lista["total"] == 2
    assert tempo_lista < 0.8, f"ad_list_ad_servers esperou {tempo_lista:.2f}s pelo AD lento"


def test_dois_ads_respondem_em_paralelo(tmp_path):
    srv = servidor_com(tmp_path, {"alfa": lambda b: pessoas(b, atraso=0.4),
                                  "beta": lambda b: pessoas(b, atraso=0.4)})

    async def cenario():
        inicio = time.monotonic()
        await asyncio.gather(*[
            chamar(srv, "ad_get_user_group_memberships", ad_server=nome,
                   username="sabrina.rocha") for nome in ("alfa", "beta")])
        return time.monotonic() - inicio

    # Each call does two searches (resolve + tool): ~0.8 s alone, ~0.8 s together.
    assert asyncio.run(cenario()) < 1.4


def test_cliente_nunca_ve_o_ad_de_outro_sob_concorrencia(tmp_path):
    srv = servidor_com(tmp_path, {"alfa": pessoas, "beta": pessoas})
    vistos = []

    def spy(params):
        antes = srv.config.active_directory.domain
        time.sleep(0.05)
        depois = srv.config.active_directory.domain
        vistos.append((srv._bound_server, antes, depois, srv.ldap_manager))
        return {"ok": True}

    srv.tools["ad_search_directory_users"]["handler"] = spy

    async def cenario():
        await asyncio.gather(*[
            chamar(srv, "ad_get_user_details_by_username", ad_server=nome,
                   username="sabrina.rocha")
            for nome in ["alfa", "beta"] * 6])

    asyncio.run(cenario())
    assert len(vistos) == 12
    for servidor, antes, depois, ldap in vistos:
        assert antes == depois == f"{servidor}.local"
        assert ldap is srv.pool.resolve_or_error(servidor)[0].ldap_manager
    # Nothing leaks into the shared object after the calls.
    assert srv._bound_server is None and srv.config is None


# --------------------------------------------------------------- busca em "todos"

def test_todos_em_paralelo_com_prazo(tmp_path):
    srv = servidor_com(tmp_path, {
        "alfa": pessoas,
        "beta": lambda b: pessoas(b, atraso=3),
        "gama": lambda b: pessoas(b, falha="AD sem conexao: 10.0.0.9:636 nao respondeu"),
    })
    srv._PRAZO_TODOS, srv._GRACA_APOS_ACHADO = 1.0, 5.0
    inicio = time.monotonic()
    r = asyncio.run(chamar(srv, "ad_get_user_details_by_username", username="Sabrina Rocha",
                           ad_server="todos"))
    assert time.monotonic() - inicio < 1.6
    assert r["encontrado_em"] == ["alfa"]
    falhas = {f["ad_server"]: f for f in r["servidores_com_falha"]}
    assert falhas["beta"]["erro"] == "TEMPO_ESGOTADO"
    assert "NAO foi verificado" in falhas["beta"]["mensagem"]
    assert falhas["gama"]["mensagem"], "a falha nunca pode chegar vazia"
    assert "gama" not in r["sem_resultado_em"]


def test_apos_achar_espera_pouco_pelos_outros(tmp_path):
    srv = servidor_com(tmp_path, {"alfa": pessoas, "beta": lambda b: pessoas(b, atraso=3)})
    srv._PRAZO_TODOS, srv._GRACA_APOS_ACHADO = 15.0, 0.4
    inicio = time.monotonic()
    r = asyncio.run(chamar(srv, "ad_get_user_details_by_username", username="Sabrina Rocha",
                           ad_server="todos"))
    assert time.monotonic() - inicio < 1.2
    assert r["encontrado_em"] == ["alfa"]
    beta = r["servidores_com_falha"][0]
    assert beta["ad_server"] == "beta" and "apos o primeiro resultado" in beta["mensagem"]


def test_ad_que_nao_responde_nao_vira_sem_resultado(tmp_path):
    srv = servidor_com(tmp_path, {"alfa": pessoas, "beta": pessoas})

    def spy(params):
        if srv._bound_server == "beta":
            return {"success": False, "error": "AD sem conexao", "type": "LDAPException"}
        return {"success": False, "error": "User 'x' not found"}

    srv.tools["ad_search_directory_users"]["handler"] = spy
    r = asyncio.run(chamar(srv, "ad_get_user_details_by_username", username="sabrina.rocha",
                           ad_server="todos"))
    assert r["sem_resultado_em"] == ["alfa"]
    assert [f["ad_server"] for f in r["servidores_com_falha"]] == ["beta"]
    assert r["servidores_com_falha"][0]["mensagem"] == "AD sem conexao"


# ------------------------------------------------------------ prazo por chamada

@pytest.mark.parametrize("tool,escrita", [
    ("ad_search_directory_users", False),
    ("ad_manage_directory_users", True),
])
def test_prazo_da_chamada_responde_antes_do_cliente(tmp_path, tool, escrita):
    srv = servidor_com(tmp_path, {"alfa": pessoas})
    srv._PRAZO_CHAMADA = 0.3

    def lento(params):
        time.sleep(1.0)
        return {"ok": True}

    srv.tools[tool]["handler"] = lento
    inicio = time.monotonic()
    extras = {"action": "disable", "client_confirmation": "alfa"} if escrita else {}
    r = asyncio.run(chamar(srv, tool, ad_server="alfa", username="sabrina.rocha", **extras))
    assert time.monotonic() - inicio < 0.8
    assert r["erro"] == "TEMPO_ESGOTADO" and r["ad_server"] == "alfa"
    assert ("PODE ter sido aplicada" in r["mensagem"]) is escrita


def test_escritas_no_mesmo_ad_uma_por_vez_leituras_em_paralelo(tmp_path):
    srv = servidor_com(tmp_path, {"alfa": pessoas, "beta": pessoas})
    ativas, pico = {}, {}
    trava = threading.Lock()

    def registrar(params):
        chave = (srv._bound_server, params.get("_tipo", "escrita"))
        with trava:
            ativas[srv._bound_server] = ativas.get(srv._bound_server, 0) + 1
            pico[srv._bound_server] = max(pico.get(srv._bound_server, 0),
                                          ativas[srv._bound_server])
        time.sleep(0.2)
        with trava:
            ativas[srv._bound_server] -= 1
        return {"ok": True, "chave": str(chave)}

    srv.tools["ad_manage_directory_users"]["handler"] = registrar

    async def cenario():
        inicio = time.monotonic()
        await asyncio.gather(*[
            chamar(srv, "ad_manage_directory_users", ad_server=nome, action="disable",
                   client_confirmation=nome, username="sabrina.rocha")
            for nome in ("alfa", "alfa", "alfa", "beta")])
        return time.monotonic() - inicio

    tempo = asyncio.run(cenario())
    assert pico["alfa"] == 1, "duas escritas no mesmo AD ao mesmo tempo"
    assert tempo < 0.9, "escrita em outro AD nao deveria esperar"


# ------------------------------------------------- disjuntor da conexao LDAP

def _gerenciador(monkeypatch, tentativa=0.15, orcamento=0.5, pausa=30.0):
    chamadas = []

    class ConexaoMorta:
        def __init__(self, server, **kwargs):
            chamadas.append(kwargs.get("receive_timeout"))
            time.sleep(tentativa)
            raise LDAPSocketOpenError("invalid server address")

    monkeypatch.setattr(lm, "Connection", ConexaoMorta)
    monkeypatch.setattr(lm, "ORCAMENTO_CONEXAO", orcamento)
    monkeypatch.setattr(lm, "TENTATIVA_MAXIMA", 1.0)
    monkeypatch.setattr(lm, "PAUSA_APOS_FALHA", pausa)
    ad = SimpleNamespace(server="ldaps://10.0.0.9:636", server_pool=[], timeout=30,
                         receive_timeout=10, bind_dn="x", password="x", auto_bind=False,
                         base_dn=BASE)
    seguranca = SimpleNamespace(enable_tls=False, validate_certificate=False, ca_cert_file=None)
    desempenho = SimpleNamespace(max_retries=3, retry_delay=0.05, page_size=500,
                                 keepalive_enabled=False, keepalive_interval=300)
    return lm.LDAPManager(ad, seguranca, desempenho), chamadas


def test_ad_morto_falha_dentro_do_orcamento(monkeypatch):
    gerente, chamadas = _gerenciador(monkeypatch)
    inicio = time.monotonic()
    with pytest.raises(LDAPException) as erro:
        gerente.connect()
    assert time.monotonic() - inicio < 0.9
    texto = str(erro.value)
    assert "10.0.0.9:636" in texto and "VPN" in texto
    assert chamadas, "tentou ao menos uma vez"


def test_segunda_chamada_ao_ad_morto_falha_na_hora(monkeypatch):
    gerente, chamadas = _gerenciador(monkeypatch)
    with pytest.raises(LDAPException):
        gerente.connect()
    feitas = len(chamadas)
    inicio = time.monotonic()
    with pytest.raises(lm.ADIndisponivel) as erro:
        gerente.connect()
    assert time.monotonic() - inicio < 0.05
    assert len(chamadas) == feitas, "nao pode tentar de novo durante a pausa"
    assert "Nova tentativa automatica" in str(erro.value)
    assert gerente.estado_de_disponibilidade()["indisponivel"] is True


def test_apos_a_pausa_tenta_de_novo(monkeypatch):
    gerente, chamadas = _gerenciador(monkeypatch, pausa=0.1)
    with pytest.raises(LDAPException):
        gerente.connect()
    feitas = len(chamadas)
    time.sleep(0.15)
    with pytest.raises(LDAPException):
        gerente.connect()
    assert len(chamadas) > feitas


def test_chamadas_simultaneas_ao_ad_morto_nao_se_somam(monkeypatch):
    gerente, _ = _gerenciador(monkeypatch)
    tempos = []

    def tentar():
        inicio = time.monotonic()
        try:
            gerente.connect()
        except LDAPException:
            pass
        tempos.append(time.monotonic() - inicio)

    threads = [threading.Thread(target=tentar) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    # One pays the budget; the others wait for it and then fail at once.
    assert max(tempos) < 1.0


def test_operacoes_no_mesmo_ad_nao_se_misturam(monkeypatch):
    gerente, _ = _gerenciador(monkeypatch)
    ativas, pico = [0], [0]
    trava = threading.Lock()

    class ConexaoViva:
        bound = True
        entries = []
        result = {"result": 0, "controls": {}}

        def search(self, **kwargs):
            with trava:
                ativas[0] += 1
                pico[0] = max(pico[0], ativas[0])
            time.sleep(0.05)
            with trava:
                ativas[0] -= 1
            return True

    gerente._connection = ConexaoViva()
    threads = [threading.Thread(target=gerente.search, args=(BASE, "(objectClass=*)"))
               for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert pico[0] == 1, "a conexao ldap3 nao e thread-safe; uma operacao por vez"


# ------------------------------------- nenhuma tool quebra no despacho novo

def _argumentos(nome, schema):
    exemplos = {
        "username": "novo.usuario" if "create" in nome else "Sabrina Rocha",
        "password": "Senha#Forte2026", "first_name": "Novo", "last_name": "Usuario",
        "group_name": "Grupo Novo" if "create" in nome else "TI Suporte",
        "computer_name": "PC-NOVO" if "create" in nome else "FIN-PC01",
        "member_dn": "Sabrina Rocha", "members": "Sabrina Rocha", "ou_dn": "_DESATIVADOS",
        "new_parent_dn": "_DESATIVADOS", "name": "OU Nova",
        "attributes": {"description": "teste"}, "server_name": "alfa",
        "client_name": "alfa", "days": 90, "report": "domain_policy",
    }
    # manage_* tools take an action; pick one whose requirements the examples
    # above already satisfy, so the dispatch really runs.
    acoes = {
        "ad_manage_directory_users": ("disable", {}),
        "ad_manage_directory_groups": ("add_members", {"members": "Sabrina Rocha"}),
        "ad_manage_directory_computers": ("disable", {}),
        "ad_manage_organizational_units": ("update", {"description": "teste"}),
    }
    args = {}
    for parametro in schema.get("required", []):
        if parametro == "ad_server":
            continue
        if parametro == "action":
            args["action"] = acoes[nome][0]
        else:
            args[parametro] = exemplos[parametro]
    args.update(acoes.get(nome, ("", {}))[1])
    if "client_confirmation" in (schema.get("properties") or {}):
        args["client_confirmation"] = "alfa"
    return args


def _servidor_padrao(tmp_path):
    bloco = _bloco("alfa")[1]
    bloco["active_directory"]["base_dn"] = BASE
    bloco["active_directory"]["domain"] = "alfa.local"
    caminho = tmp_path / "s.json"
    caminho.write_text(json.dumps({"version": 1, "servers": {"alfa": bloco}}), encoding="utf-8")
    srv = ActiveDirectoryMCPFastAPI(port=0, servers_path=str(caminho), mode="multi")
    bundle, _ = srv.pool.resolve_or_error("alfa")
    falso = diretorio_padrao()
    bundle.ldap_manager = falso
    for conjunto in _TOOLSETS:
        getattr(bundle, conjunto).ldap = falso
    return srv


def _nomes_das_tools(multi):
    srv = ActiveDirectoryMCPFastAPI.__new__(ActiveDirectoryMCPFastAPI)
    srv.multi, srv.pool, srv.security_manager = multi, None, None
    srv.logger = __import__("logging").getLogger("teste")
    for nome in ActiveDirectoryMCPFastAPI._TENANT_ATTRS:
        setattr(srv, nome, None)
    srv._build_tool_registry()
    return sorted(srv.tools)


@pytest.mark.parametrize("tool", _nomes_das_tools(True))
def test_toda_tool_roda_no_despacho_multi(tmp_path, tool):
    srv = _servidor_padrao(tmp_path)
    schema = srv.tools[tool]["inputSchema"]
    args = _argumentos(tool, schema)
    if "ad_server" in schema.get("properties", {}):
        args["ad_server"] = "alfa"
    r = asyncio.run(srv.handle_tools_call({"name": tool, "arguments": args}))
    texto = r["content"][0]["text"]
    json.loads(texto)
    assert "'NoneType' object has no attribute" not in texto, texto[:300]
    assert "TEMPO_ESGOTADO" not in texto


@pytest.mark.parametrize("tool", [t for t in _nomes_das_tools(True)
                                  if t.startswith("ad_search_")
                                  and t not in ActiveDirectoryMCPFastAPI._GLOBAL_TOOLS])
def test_toda_leitura_roda_em_todos(tmp_path, tool):
    srv = _servidor_padrao(tmp_path)
    schema = srv.tools[tool]["inputSchema"]
    args = _argumentos(tool, schema)
    args["ad_server"] = "todos"
    r = asyncio.run(srv.handle_tools_call({"name": tool, "arguments": args}))
    texto = r["content"][0]["text"]
    corpo = json.loads(texto)
    assert "'NoneType' object has no attribute" not in texto, texto[:300]
    assert corpo.get("servidores_consultados") == 1 or corpo.get("erro"), corpo


@pytest.mark.parametrize("tool", _nomes_das_tools(False))
def test_toda_tool_roda_no_despacho_single(tool):
    falso = diretorio_padrao()
    srv = ActiveDirectoryMCPFastAPI.__new__(ActiveDirectoryMCPFastAPI)
    srv.multi, srv.pool, srv.security_manager = False, None, None
    srv.mode = "single"
    srv.logger = __import__("logging").getLogger("teste")
    srv.config = SimpleNamespace(active_directory=SimpleNamespace(base_dn=BASE,
                                                                  domain="alfa.local",
                                                                  server="ldaps://x"))
    srv.ldap_manager = falso
    srv.user_tools, srv.group_tools = UserTools(falso), GroupTools(falso)
    srv.computer_tools, srv.ou_tools = ComputerTools(falso), OrganizationalUnitTools(falso)
    srv.security_tools = SecurityTools(falso)
    srv._build_tool_registry()
    args = _argumentos(tool, srv.tools[tool]["inputSchema"])
    r = asyncio.run(srv.handle_tools_call({"name": tool, "arguments": args}))
    texto = r["content"][0]["text"]
    json.loads(texto)
    assert "'NoneType' object has no attribute" not in texto, texto[:300]


# ---------------------------------------- conexao fria nao e "tempo esgotado"

def test_ad_saudavel_mas_frio_nao_e_cortado_pela_graca(tmp_path):
    """Measured in production 2026-09-21: one directory answered in 49 ms
    because it was already connected, which started the 3 s grace -- and three
    HEALTHY directories were reported as "tempo esgotado" while still opening
    their first connection."""
    srv = servidor_com(tmp_path, {"alfa": pessoas, "beta": pessoas})
    conectados = {"alfa"}
    srv.pool.esta_conectado = lambda chave: chave in conectados

    def handler(params):
        if srv._bound_server != "alfa":
            time.sleep(4.0)          # cold: TLS handshake + bind
            conectados.add(srv._bound_server)
        return {"users": [{"sAMAccountName": "sabrina.rocha"}]}

    for nome in ("ad_search_directory_users",):
        srv.tools[nome]["handler"] = handler
    srv._PRAZO_CONEXAO_FRIA = 6.0
    r = asyncio.run(chamar(srv, "ad_search_directory_users", ad_server="todos",
                           username="sabrina.rocha"))
    assert set(r["encontrado_em"]) == {"alfa", "beta"}, r
    assert not r.get("servidores_com_falha")


def test_quando_todos_estao_quentes_a_graca_curta_vale(tmp_path):
    srv = servidor_com(tmp_path, {"alfa": pessoas, "beta": pessoas})
    srv.pool.esta_conectado = lambda chave: True
    srv._GRACA_APOS_ACHADO = 0.3

    def handler(params):
        if srv._bound_server != "alfa":
            time.sleep(2.0)
        return {"users": [{"sAMAccountName": "sabrina.rocha"}]}

    srv.tools["ad_search_directory_users"]["handler"] = handler
    inicio = time.monotonic()
    r = asyncio.run(chamar(srv, "ad_search_directory_users", ad_server="todos",
                           username="sabrina.rocha"))
    assert time.monotonic() - inicio < 1.5
    assert r["servidores_com_falha"][0]["erro"] == "TEMPO_ESGOTADO"
