"""stdio transport for the Active Directory MCP server.

This file used to carry its own copy of every tool: 40 decorated functions
with their own parameter texts, plus a hook that re-applied the shared
descriptions and the identifier resolver on top of them. The two transports
drifted apart anyway (the stdio copy still asked the model to "confirme
cliente primeiro" long after that became configurable), and every tool added
to one had to be added to the other.

It is now a transport and nothing else: the catalogue, the input sanitizing,
the name resolution, the write policy and the deadlines all live in
ActiveDirectoryMCPFastAPI, which runs here in single-AD mode. What stdio
clients see is exactly what HTTP clients see -- there is no second place for
the behaviour to drift into.

Everything written to stdout here would corrupt the JSON-RPC stream, so logs
go to stderr (core/logging.py).
"""

import asyncio
import os
import signal
import sys
from typing import Any, Dict, List, Optional

import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from .server_fastapi import ActiveDirectoryMCPFastAPI
from .tools.definitions import INSTRUCOES_DO_SERVIDOR


class ActiveDirectoryMCPServer:
    """Serve the shared tool catalogue over stdio."""

    def __init__(self, config_path: Optional[str] = None):
        # mode="single": one directory per process, as this transport always
        # worked. port=0 because no socket is opened -- only the registry,
        # the tools and the LDAP manager are used.
        self.nucleo = ActiveDirectoryMCPFastAPI(config_path=config_path, mode="single", port=0)
        self.logger = self.nucleo.logger
        self.app = Server("mcp-active-directory", instructions=INSTRUCOES_DO_SERVIDOR)
        self._registrar()

    # The pieces this class used to own live in the core now; exposing them
    # keeps `server.user_tools`, `server.config` and friends working for
    # callers and tests that reach in.
    _DO_NUCLEO = ("config", "ldap_manager", "security_manager", "user_tools", "group_tools",
                  "computer_tools", "ou_tools", "security_tools", "tools", "multi", "pool")

    def __getattr__(self, nome: str) -> Any:
        if nome in self._DO_NUCLEO:
            return getattr(self.__dict__["nucleo"], nome)
        raise AttributeError(nome)

    # ------------------------------------------------------------- catalogue

    def _tools(self) -> List[types.Tool]:
        tools = []
        for nome, tool in self.nucleo.tools.items():
            if tool.get("oculta"):
                continue
            anotacoes = tool.get("annotations") or {}
            tools.append(types.Tool(
                name=nome,
                description=tool["description"],
                inputSchema=tool["inputSchema"],
                annotations=types.ToolAnnotations(**anotacoes) if anotacoes else None,
            ))
        return tools

    @staticmethod
    def _como_conteudo(resposta: Dict[str, Any]) -> List[types.TextContent]:
        return [types.TextContent(type="text", text=item.get("text", ""))
                for item in resposta.get("content", [])]

    def _registrar(self) -> None:
        @self.app.list_tools()
        async def listar_tools() -> List[types.Tool]:
            return self._tools()

        @self.app.call_tool()
        async def chamar_tool(name: str, arguments: Optional[Dict[str, Any]]):
            resposta = await self.nucleo.handle_tools_call(
                {"name": name, "arguments": arguments or {}})
            return self._como_conteudo(resposta)

        @self.app.list_prompts()
        async def listar_prompts() -> List[types.Prompt]:
            catalogo = await self.nucleo.handle_prompts_list({})
            return [types.Prompt(
                name=p["name"],
                description=p.get("description", ""),
                arguments=[types.PromptArgument(
                    name=a["name"],
                    description=a.get("description", ""),
                    required=bool(a.get("required")),
                ) for a in (p.get("arguments") or [])],
            ) for p in catalogo.get("prompts", [])]

        @self.app.get_prompt()
        async def obter_prompt(name: str, arguments: Optional[Dict[str, Any]]):
            resultado = await self.nucleo.handle_prompts_get(
                {"name": name, "arguments": arguments or {}})
            mensagens = []
            for mensagem in resultado.get("messages", []):
                conteudo = mensagem.get("content") or {}
                mensagens.append(types.PromptMessage(
                    role=mensagem.get("role", "user"),
                    content=types.TextContent(type="text", text=conteudo.get("text", "")),
                ))
            return types.GetPromptResult(
                description=resultado.get("description", ""), messages=mensagens)

    # ----------------------------------------------------------------- run

    async def _servir(self) -> None:
        async with stdio_server() as (leitura, escrita):
            await self.app.run(
                leitura, escrita,
                InitializationOptions(
                    server_name="mcp-active-directory",
                    server_version="1.1.0",
                    capabilities=self.app.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                    instructions=INSTRUCOES_DO_SERVIDOR,
                ),
            )

    def start(self) -> None:
        """Run until a signal or a fatal error."""
        def encerrar(signum, frame):  # noqa: ARG001 - signal handler signature
            self.logger.info("Signal %s received, shutting down", signum)
            self.nucleo._shutdown_connections()
            sys.exit(0)

        signal.signal(signal.SIGINT, encerrar)
        signal.signal(signal.SIGTERM, encerrar)
        self.logger.info("Active Directory MCP (stdio) ready: %d tools",
                         len(self._tools()))
        try:
            asyncio.run(self._servir())
        except KeyboardInterrupt:
            pass
        except Exception as exc:  # noqa: BLE001 - last resort, reported on stderr
            self.logger.error("Server error: %s", exc)
            self.nucleo._shutdown_connections()
            sys.exit(1)


def main():
    """Main entry point for the server."""
    config_path = os.getenv("AD_MCP_CONFIG")
    if not config_path:
        print("AD_MCP_CONFIG environment variable must be set", file=sys.stderr)
        sys.exit(1)

    try:
        ActiveDirectoryMCPServer(config_path).start()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - startup failure, reported on stderr
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
