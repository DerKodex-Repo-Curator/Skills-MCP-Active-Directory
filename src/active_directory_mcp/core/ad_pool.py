"""Pool of Active Directory servers for multi-AD mode.

One process, N directories. Each configured server gets its own lazily built
bundle: an ``LDAPManager``, the six tool sets and its own security manager.

Nothing here changes single-AD behaviour: the pool is only instantiated when
``AD_MCP_MODE=multi``.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..config.models import Config
from ..config.multi_loader import ADServerEntry, normalize_name
from .client_security import ClientSecurityManager
from .ldap_manager import LDAPManager
from ..tools.computer import ComputerTools
from ..tools.group import GroupTools
from ..tools.organizational_unit import OrganizationalUnitTools
from ..tools.security import SecurityTools
from ..tools.user import UserTools

logger = logging.getLogger("active-directory-mcp.pool")


@dataclass
class ADBundle:
    """Everything needed to serve one Active Directory."""

    key: str
    entry: ADServerEntry
    config: Config
    ldap_manager: LDAPManager
    user_tools: UserTools
    group_tools: GroupTools
    computer_tools: ComputerTools
    ou_tools: OrganizationalUnitTools
    security_tools: SecurityTools
    security_manager: ClientSecurityManager


class ADServerPool:
    """Resolves a server name to its bundle, building it on first use."""

    def __init__(self, entries: Dict[str, ADServerEntry]):
        self.entries = entries
        self._bundles: Dict[str, ADBundle] = {}
        self._index: Dict[str, str] = {}
        for key, entry in entries.items():
            for name in entry.match_keys():
                self._index[name] = key
        logger.info(
            "Pool inicializado com %d servidores e %d nomes de busca",
            len(entries), len(self._index),
        )

    # ------------------------------------------------------------------ names

    def esta_conectado(self, key: str) -> bool:
        """Whether this directory already holds an open LDAP connection.

        Cheap and side-effect free: it never opens one. Used to tell a
        directory that is merely SLOW TO CONNECT from one that is not
        answering (see the fan-out deadline).
        """
        bundle = self._bundles.get(key)
        if bundle is None:
            return False
        try:
            return bool(bundle.ldap_manager.get_connection_stats().get("connected"))
        except Exception:  # noqa: BLE001 - unknown means "not connected"
            return False

    def aquecer(self, em_segundo_plano: bool = True) -> Optional[threading.Thread]:
        """Open every enabled directory's connection at boot.

        @MX:REASON Measured 2026-09-21 in production: a model asked for one
        account with no ad_server; one tenant answered in 49 ms because it was
        already connected, which started the 3 s grace the fan-out gives the
        others -- and three HEALTHY directories were cut while still doing
        their first TLS handshake and bind. The operator saw "tempo esgotado"
        for directories that were fine. Warming up removes the cold first call;
        the fan-out also stops counting the grace against a directory that is
        still connecting.
        """
        def trabalho():
            for key in self.available_names():
                try:
                    self._get_or_build(key).ldap_manager.connect()
                    logger.info("Conexao aquecida: %s", key)
                except Exception as exc:  # noqa: BLE001 - a dead AD must not stop the rest
                    logger.warning("Aquecimento falhou em '%s': %s", key, str(exc)[:200])

        if not em_segundo_plano:
            trabalho()
            return None
        thread = threading.Thread(target=trabalho, name="ad-aquecimento", daemon=True)
        thread.start()
        return thread

    def available_names(self, only_enabled: bool = True) -> List[str]:
        return [
            key for key, entry in self.entries.items()
            if (entry.enabled or not only_enabled)
        ]

    def _short_catalog(self) -> List[Dict[str, str]]:
        """Compact catalogue used inside error payloads (name + domain only)."""
        return [
            {"ad_server": key, "dominio": entry.domain}
            for key, entry in self.entries.items()
            if entry.enabled
        ]

    def _lookup(self, requested: str) -> Tuple[Optional[str], List[str]]:
        """Return (key, candidates). Exact match wins; unique prefix is accepted.

        @MX:ANCHOR Never returns a key when more than one server matches --
        the caller must surface the ambiguity instead of picking one.
        """
        name = normalize_name(requested)
        if not name:
            return None, []
        if name in self._index:
            return self._index[name], []
        candidates = sorted({
            key for alias, key in self._index.items() if alias.startswith(name)
        })
        if len(candidates) == 1:
            return candidates[0], []
        return None, candidates

    # --------------------------------------------------------------- resolve

    def resolve_or_error(
        self, requested: Optional[str]
    ) -> Tuple[Optional[ADBundle], Optional[Dict[str, Any]]]:
        """Resolve a server name into a bundle, or return a structured refusal.

        The refusal payload tells the model exactly what to do next, because a
        tool error is an instruction the model will act on.
        """
        if requested is None or str(requested).strip() == "":
            return None, {
                "sucesso": False,
                "erro": "AD_SERVER_NAO_INFORMADO",
                "mensagem": (
                    "Esta instancia atende varios Active Directory. Informe o parametro "
                    "'ad_server' com o servidor alvo. Nao ha servidor padrao: escolher um "
                    "por conta propria poderia ler ou gravar no AD do cliente errado."
                ),
                "servidores_disponiveis": self._short_catalog(),
                "como_descobrir": "Chame a tool ad_list_ad_servers para ver todos os servidores.",
            }

        key, candidates = self._lookup(str(requested))

        if key is None and candidates:
            return None, {
                "sucesso": False,
                "erro": "AD_SERVER_AMBIGUO",
                "mensagem": (
                    f"'{requested}' corresponde a mais de um servidor: "
                    f"{', '.join(candidates)}. Repita a chamada com o nome exato."
                ),
                "candidatos": candidates,
            }

        if key is None:
            return None, {
                "sucesso": False,
                "erro": "AD_SERVER_DESCONHECIDO",
                "mensagem": (
                    f"Nao existe servidor de AD chamado '{requested}' nesta instancia. "
                    "Isso significa que este cliente nao tem AD configurado aqui -- nao "
                    "tente outro nome parecido nem outra tool para contornar."
                ),
                "servidores_disponiveis": self._short_catalog(),
            }

        entry = self.entries[key]

        if not entry.enabled:
            return None, {
                "sucesso": False,
                "erro": "AD_SERVER_DESABILITADO",
                "mensagem": (
                    f"O servidor '{key}' existe na configuracao mas esta desabilitado "
                    "(enabled: false). Nenhuma operacao sera executada nele."
                ),
                "servidores_disponiveis": self._short_catalog(),
            }

        if not entry.valid:
            return None, {
                "sucesso": False,
                "erro": "AD_SERVER_CONFIG_INVALIDA",
                "mensagem": (
                    f"O servidor '{key}' esta declarado mas sua configuracao nao passou "
                    f"na validacao, entao ele nao pode ser usado. Motivo: {entry.error}"
                ),
                "servidores_disponiveis": self._short_catalog(),
            }

        try:
            return self._get_or_build(key), None
        except Exception as exc:
            logger.error("Falha ao inicializar o servidor '%s': %s", key, exc)
            return None, {
                "sucesso": False,
                "erro": "AD_SERVER_INDISPONIVEL",
                "mensagem": (
                    f"Nao foi possivel inicializar a conexao com o servidor '{key}': {exc}"
                ),
                "servidor": key,
            }

    def _get_or_build(self, key: str) -> ADBundle:
        """Build the bundle on first use. Failures are not cached."""
        bundle = self._bundles.get(key)
        if bundle is not None:
            return bundle

        entry = self.entries[key]
        config = entry.config
        logger.info("Inicializando servidor de AD '%s' (%s)", key, entry.domain)

        ldap_manager = LDAPManager(
            config.active_directory,
            config.security,
            config.performance,
            ou_config=config.organizational_units,
        )
        raw = dict(entry.raw)
        client = dict(raw.get("client") or {})
        client.setdefault("name", entry.label)
        client.setdefault("slug", key)
        raw["client"] = client

        bundle = ADBundle(
            key=key,
            entry=entry,
            config=config,
            ldap_manager=ldap_manager,
            user_tools=UserTools(ldap_manager),
            group_tools=GroupTools(ldap_manager),
            computer_tools=ComputerTools(ldap_manager),
            ou_tools=OrganizationalUnitTools(ldap_manager),
            security_tools=SecurityTools(ldap_manager),
            security_manager=ClientSecurityManager(raw, None),
        )
        self._bundles[key] = bundle
        return bundle

    # ---------------------------------------------------------------- status

    def _status_of(self, key: str) -> Tuple[str, Optional[str]]:
        """Report connection state WITHOUT opening a connection.

        A server that was never used reports 'nao_conectado' -- which is the
        truth, not an error and not a health claim.
        """
        entry = self.entries[key]
        if not entry.enabled:
            return "desabilitado", None
        if not entry.valid:
            return "configuracao_invalida", entry.error
        bundle = self._bundles.get(key)
        if bundle is None:
            return "nao_conectado", "Nenhuma operacao foi executada neste servidor ainda."
        estado = getattr(bundle.ldap_manager, "estado_de_disponibilidade", None)
        if callable(estado):
            disponibilidade = estado()
            if disponibilidade.get("indisponivel"):
                return "indisponivel", disponibilidade.get("ultima_falha")
        try:
            stats = bundle.ldap_manager.get_connection_stats()
            if stats.get("connected"):
                return "conectado", None
            return "desconectado", "Conexao ja foi usada mas nao esta ativa no momento."
        except Exception as exc:
            return "erro", str(exc)

    def list_servers(self) -> Dict[str, Any]:
        servers = []
        for key in self.entries:
            status, detail = self._status_of(key)
            servers.append(self.entries[key].public_info(status, detail))
        habilitados = [s for s in servers if s.get("habilitado")]
        return {
            "modo": "multi",
            "total": len(servers),
            "total_habilitados": len(habilitados),
            "servidores": servers,
            "como_usar": (
                "Passe o valor do campo 'ad_server' no parametro ad_server das demais "
                "tools. Consultas aceitam ad_server='todos' quando nao se sabe em qual AD "
                "a pessoa esta. Usuarios, grupos, computadores e OUs podem ser informados "
                "por nome, parte do nome, login, e-mail ou DN. client_confirmation so e "
                "necessario se uma resposta pedir CONFIRMACAO NECESSARIA."
            ),
            "nota_de_seguranca": (
                "Credenciais de bind nao sao expostas por esta tool."
            ),
        }

    def disconnect_all(self) -> None:
        for key, bundle in self._bundles.items():
            try:
                bundle.ldap_manager.disconnect()
            except Exception as exc:
                logger.warning("Erro ao desconectar '%s': %s", key, exc)
