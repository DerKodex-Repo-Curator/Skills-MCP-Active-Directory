"""Tool and parameter descriptions -- the single source for both transports.

server_fastapi.py (HTTP) and server.py (stdio) used to carry their own copy of
every description. They drifted: the stdio server still asked the model to
"confirme cliente primeiro" long after confirmation became configurable, and
neither said that an identifier could be anything but an exact login. Both now
read from here, and a test holds them equal.

Rules these texts follow (DIRETRIZES-OBRIGATORIAS-MCP-TOOLS-NOMENCLATURA.md,
phase 3): pt-BR, key noun first, 280-400 characters, the server named at least
twice, an explicit "Use quando" and what comes back.
"""

from typing import Any, Dict

# ------------------------------------------------------------------ tools

DESCRICOES_TOOLS: Dict[str, str] = {
    # 10 public tools: search_* (read-only) and manage_* (action) per kind of object.
    "ad_search_directory_servers": (
        "Servidores de Active Directory configurados — lista os ADs de clientes com domínio, "
        "base DN e estado; server_name confere um cliente pelo nome e test_connection=true "
        "testa a conexão LDAP (de um ou de todos). Use quando não souber qual AD atende um "
        "cliente ou quando as tools do Active Directory falharem. Não é preciso chamar antes: "
        "ad_server já aceita o nome do cliente. Somente leitura."),
    "ad_search_directory_users": (
        "Usuários, contas e colaboradores do Active Directory — com username devolve a ficha "
        "completa (grupos, grupo primário, OU, status, gestor); sem ele lista por texto "
        "livre, filtro LDAP ou OU; com inactive_days lista contas sem logon. Use quando "
        "precisar achar ou consultar pessoas no AD. Aceita login, nome completo, parte do "
        "nome, e-mail ou DN. Somente leitura."),
    "ad_manage_directory_users": (
        "Usuários do Active Directory, gestão por action: create (admissão; copy_from_user "
        "copia grupos e OU de um colega), update, move, enable, disable (desligamento com "
        "move_to_ou e remove_from_groups), reset_password e delete (exclusão permanente). Use "
        "quando precisar alterar contas de pessoas no AD. A conta aceita login ou nome "
        "inteiro; ambiguidade não executa. Devolve o estado relido. Escrita."),
    "ad_search_directory_groups": (
        "Grupos de segurança e de distribuição do Active Directory — com group_name devolve "
        "detalhes e membros (recursive=true inclui os aninhados); sem ele lista por texto "
        "livre, filtro LDAP ou OU. Use quando precisar achar um grupo, ver quem pertence a "
        "ele ou auditar acessos no AD. Aceita nome, parte do nome, login ou DN; ambíguo "
        "devolve candidatos. Somente leitura."),
    "ad_manage_directory_groups": (
        "Grupos do Active Directory, gestão por action: create, update, move, add_members e "
        "remove_members (vários grupos e membros numa chamada) e delete (exclusão "
        "permanente). Use quando precisar dar ou tirar acesso, criar ou ajustar grupos de "
        "segurança e listas de e-mail no AD. Grupo e membros aceitam nome, login ou DN; "
        "ambiguidade não executa. Devolve o relido. Escrita."),
    "ad_search_directory_computers": (
        "Computadores, estações e servidores do Active Directory — com computer_name devolve "
        "os detalhes da máquina; sem ele lista por texto livre, filtro LDAP ou OU; com "
        "inactive_days lista máquinas sem logon. Use quando precisar achar, inventariar ou "
        "limpar computadores do AD. Aceita nome, parte do nome, FQDN ou DN. Somente leitura."),
    "ad_manage_directory_computers": (
        "Computadores do Active Directory, gestão por action: create (pré-cadastro), update, "
        "move, enable, disable, reset_trust (corrige a relação de confiança) e delete "
        "(exclusão permanente). Use quando precisar provisionar, bloquear ou corrigir uma "
        "estação ou servidor no AD. Aceita nome, FQDN ou DN; controlador de domínio é "
        "recusado. Escrita."),
    "ad_search_organizational_units": (
        "Unidades organizacionais (OUs) do Active Directory — com ou_dn devolve detalhes, "
        "GPOs e o conteúdo (usuários, grupos, computadores, sub-OUs); sem ele lista a "
        "hierarquia com busca por nome. Use quando precisar achar a OU de um setor, de uma "
        "filial ou de desativados no AD. Aceita nome, caminho (Filial/TI) ou DN. Somente "
        "leitura."),
    "ad_manage_organizational_units": (
        "Unidades organizacionais (OUs) do Active Directory, gestão por action: create, "
        "update, move (nova OU-pai) e delete (exclusão permanente; force apaga o conteúdo). "
        "Use quando precisar estruturar pastas, setores ou filiais no AD. A OU aceita nome, "
        "caminho completo (Filial/TI) ou DN; caminho incompleto ou nome repetido não "
        "executam. Escrita."),
    "ad_search_security_reports": (
        "Relatórios de segurança do Active Directory — report escolhe: domain_policy (senha e "
        "bloqueio), privileged_groups (Domain Admins e afins), admin_accounts (auditoria de "
        "administradores), password_violations e user_permissions (acessos de uma pessoa, por "
        "login ou nome). Use quando precisar auditar segurança, privilégios ou senhas no AD. "
        "Somente leitura."),

    # Not listed; reached through the aliases of old tool names.
    "ad_test_ldap_connection_status": (
        "Conexão e saúde do MCP de Active Directory — testa conectividade, bind e busca no "
        "controlador de domínio de um cliente; sem ad_server, testa todos os ADs de uma vez. "
        "Use quando as tools do AD falharem, houver erro de conexão ou for preciso validar o "
        "acesso ao servidor de um cliente. Retorna status da conexão, do bind e do teste de "
        "busca. Diagnóstico somente leitura."),
    "ad_move_organizational_unit_parent": (
        "Usuário, computador, grupo ou OU no Active Directory, mudança de OU — move o objeto "
        "para outra unidade organizacional, como trocar alguém de setor ou de filial. Use "
        "quando precisar só mover um objeto no AD; para desligar e mover de uma vez, use "
        "ad_manage_directory_users, action=disable, com move_to_ou. Objeto e destino aceitam "
        "nome, login, caminho ou DN. Retorna o DN novo relido. Escrita."),
}

# ------------------------------------------------------------- parameters

_EXISTENTE = (
    " Acento e maiúscula não importam. Em escrita só vale identificador exato ou palavras "
    "inteiras do nome; abreviação, trecho ou mais de um objeto devolvem candidatos sem executar.")

DESCRICOES_PARAMETROS: Dict[str, str] = {
    "username": (
        "Usuário existente. Aceita login (sAMAccountName), nome completo, parte do nome em "
        "qualquer ordem, e-mail, UPN, DOMINIO\\usuario ou DN." + _EXISTENTE),
    "group_name": (
        "Grupo existente. Aceita nome do grupo, parte do nome, login do grupo "
        "(sAMAccountName) ou DN." + _EXISTENTE),
    "computer_name": (
        "Computador existente. Aceita nome da máquina, parte do nome, nome DNS completo "
        "(FQDN), login com $ ou DN." + _EXISTENTE),
    "member_dn": (
        "Membro a incluir ou retirar: usuário, grupo ou computador. Não precisa ser DN: "
        "aceita login, nome completo, parte do nome, e-mail ou DN." + _EXISTENTE),
    "managed_by": (
        "Responsável: usuário ou grupo, por login, nome, parte do nome ou DN."),
    "object_name": (
        "Objeto a mover: usuário, computador, grupo ou OU, por login, nome, caminho de OU "
        "(Filial/TI) ou DN. Use object_type se o mesmo nome existir em mais de um tipo."
        + _EXISTENTE),
    "object_type": (
        "Restringe object_name a um tipo. Valores aceitos: user (usuário), computer "
        "(computador), group (grupo), organizational_unit (OU)."),
    "ou": (
        "OU onde procurar: nome (ex.: Financeiro), caminho (ex.: Filial/Financeiro) ou DN. "
        "Omitido: o domínio inteiro."),
    "parent_ou": (
        "OU a partir da qual listar: nome, caminho (ex.: Filial/Financeiro) ou DN. Omitido: "
        "a raiz do domínio."),
    "ou_dn": (
        "OU existente: nome (ex.: _DESATIVADOS), caminho (ex.: Filial/Financeiro) ou DN. "
        "Nome repetido em mais de um lugar devolve os candidatos."),
    "new_parent_dn": (
        "OU de destino: nome (ex.: _DESATIVADOS), caminho (ex.: Filial/TI) ou DN."),
    "filter_criteria": (
        "Busca: texto livre (parte do nome, login ou e-mail, palavras em qualquer ordem) ou "
        "filtro LDAP entre parênteses, ex.: (department=Financeiro)."),
    "attributes": (
        "Atributos LDAP a devolver, ex.: [\"mail\", \"department\"]. Omitido: o conjunto "
        "padrão da tool."),
    "additional_attributes": (
        "Atributos LDAP extras na criação, no formato {\"atributo\": valor}. manager e "
        "managedBy aceitam nome ou login."),
    "password": "Senha inicial da nova conta. Precisa atender à política de senha do domínio.",
    "first_name": "create: nome (givenName) da pessoa.",
    "last_name": "create: sobrenome (sn) da pessoa.",
    "email": "create: e-mail (mail) da nova conta.",
    "password_never_expires": (
        "reset_password: true marca a senha como 'nunca expira' (anula a troca obrigatória; "
        "o servidor informa)."),
    "display_name": "Nome de exibição do grupo.",
    "description": "Descrição do objeto.",
    "group_scope": "Escopo do grupo. Valores aceitos: Global (padrão), DomainLocal, Universal.",
    "group_type": (
        "Tipo do grupo. Valores aceitos: Security (segurança, padrão), Distribution "
        "(distribuição, lista de e-mail)."),
    "dns_hostname": "Nome DNS completo (FQDN) da máquina, ex.: pc01.empresa.local.",
    "include_disabled": "true: inclui contas já desativadas no resultado.",
    "action": "O que fazer. Valores aceitos: veja o enum.",
    "report": (
        "Qual relatório: domain_policy, privileged_groups, admin_accounts, password_violations "
        "ou user_permissions (exige username)."),
    "test_connection": (
        "true: testa a conexão LDAP do servidor em server_name, ou de todos se omitido."),
    "inactive_days": (
        "Lista só as contas sem logon há mais do que estes dias, entre 1 e 36500. Ex.: 90."),
    "members": (
        "Membro(s) para add_members/remove_members: um ou uma lista de usuários, grupos ou "
        "computadores. Aceita login, nome completo, parte do nome, e-mail ou DN." + _EXISTENTE),
    "copy_from_user": (
        "create: conta modelo existente, ex.: a pessoa substituída. Copia os grupos dela e, se ou for "
        "omitido, a OU. Aceita login, nome completo, palavras inteiras do nome, e-mail ou DN."
        + _EXISTENTE),
    "must_change_password": (
        "create e reset_password: true (padrão) exige a troca da senha no próximo logon."),
    "move_to_ou": (
        "OU de destino em move, update e disable (desligamento), ex.: _DESATIVADOS. Aceita "
        "nome, caminho (Filial/TI) ou DN. Omitido: o objeto fica onde está."),
    "remove_from_groups": (
        "disable: true retira a conta de todos os grupos diretos e devolve a lista removida "
        "(o grupo primário fica). false (padrão): mantém os grupos."),
    "recursive": "true: inclui também os níveis aninhados.",
    "name": "Nome da nova OU, ex.: Financeiro.",
    "force": "delete: true apaga também tudo o que estiver dentro da OU. Irreversível.",
    "object_types": (
        "Tipos de objeto a listar. Valores aceitos: user, group, computer, "
        "organizationalUnit. Omitido: todos."),
    "server_name": (
        "Nome do cliente, apelido ou domínio a conferir, ex.: Empresa Alfa. Omitido: lista "
        "todos."),
    "automation_token": (
        "Token de automação para rotinas sem operador. Não use em conversa com usuário."),
    "client_confirmation": (
        "Só quando uma resposta deste servidor pedir CONFIRMACAO NECESSARIA: informe o nome "
        "do cliente ou o ad_server. Caso contrário, omita."),
}

# Same parameter name, different meaning in a given tool.
DESCRICOES_PARAMETROS_POR_TOOL: Dict[str, Dict[str, str]] = {
    "ad_search_directory_users": {
        "username": (
            "Pessoa a consultar (ficha completa). Aceita login, nome completo, parte do nome, "
            "e-mail, UPN ou DN; ambíguo devolve candidatos. Omitido: lista."),
    },
    "ad_manage_directory_users": {
        "action": (
            "create (exige password, first_name, last_name), update (attributes e/ou "
            "move_to_ou), move (move_to_ou), enable, disable (opcional move_to_ou e "
            "remove_from_groups), reset_password (password opcional: omitida, é gerada), "
            "delete."),
        "username": (
            "Conta alvo. Em create, o login NOVO (ex.: joana.lima). Nas demais actions, a conta "
            "existente por login, nome completo, palavras inteiras do nome, e-mail ou DN."
            + _EXISTENTE),
        "password": (
            "create: senha inicial (obrigatória; política do domínio). reset_password: nova "
            "senha; omitida, o servidor gera e devolve."),
        "ou": (
            "create: OU onde criar, por nome, caminho (Filial/Financeiro) ou DN. Omitido: a OU "
            "de copy_from_user ou, sem modelo, a OU padrão."),
        "attributes": (
            "create e update: campos a gravar, {\"campo\": valor}. Aceita nomes LDAP ou do "
            "PowerShell (Office, City, Title...). Em update, \"\" apaga o campo e null é "
            "ignorado; manager aceita nome."),
    },
    "ad_search_directory_groups": {
        "group_name": (
            "Grupo a detalhar, com os membros. Aceita nome, parte do nome, login ou DN; "
            "ambíguo devolve candidatos. Omitido: lista."),
        "recursive": "true: expande os grupos aninhados e lista também os membros indiretos.",
    },
    "ad_manage_directory_groups": {
        "action": (
            "create, update (attributes/description e/ou move_to_ou), move (move_to_ou), "
            "add_members e remove_members (members), delete."),
        "group_name": (
            "Em create, o nome do NOVO grupo. Nas demais, o grupo existente por nome, login ou "
            "DN; em add_members/remove_members aceita lista." + _EXISTENTE),
        "ou": "create: OU onde criar, por nome, caminho (Filial/TI) ou DN. Omitido: a padrão.",
        "attributes": (
            "create e update: campos LDAP a gravar, {\"campo\": valor}. managedBy aceita nome "
            "ou login."),
    },
    "ad_search_directory_computers": {
        "computer_name": (
            "Máquina a detalhar. Aceita nome, parte do nome, FQDN ou DN; ambígua devolve "
            "candidatos. Omitido: lista."),
    },
    "ad_manage_directory_computers": {
        "action": (
            "create, update (attributes/description e/ou move_to_ou), move (move_to_ou), "
            "enable, disable, reset_trust, delete."),
        "computer_name": (
            "Em create, o nome da NOVA máquina, sem $ (ex.: FIN-PC03). Nas demais, a máquina "
            "existente por nome, FQDN ou DN." + _EXISTENTE),
        "ou": "create: OU onde criar, por nome, caminho (Filial/TI) ou DN. Omitido: a padrão.",
        "attributes": (
            "create e update: campos LDAP a gravar, {\"campo\": valor}, ex.: {\"location\": "
            "\"Sala 2\"}. managedBy aceita nome ou login."),
    },
    "ad_search_organizational_units": {
        "ou_dn": (
            "OU a detalhar com o conteúdo: nome (ex.: _DESATIVADOS), caminho ou DN. Omitido: "
            "lista a hierarquia."),
        "recursive": "true (padrão): inclui as sub-OUs de todos os níveis; false: só o primeiro.",
    },
    "ad_manage_organizational_units": {
        "action": (
            "create (name, parent_ou), update (attributes/description e/ou move_to_ou), move "
            "(ou_dn e move_to_ou), delete (ou_dn; force apaga o conteúdo)."),
        "ou_dn": (
            "OU existente alvo de update, move ou delete: nome, caminho ou DN. Nome repetido "
            "em mais de um lugar devolve os candidatos."),
        "name": "create: nome da nova OU, ex.: Financeiro.",
        "parent_ou": "create: OU-pai da nova OU, por nome, caminho ou DN. Omitido: a raiz.",
        "move_to_ou": "move e update: nova OU-pai, por nome, caminho (Filial/TI) ou DN.",
        "attributes": (
            "create e update: campos a gravar, {\"campo\": valor}. managedBy aceita nome ou "
            "login."),
    },
    "ad_search_security_reports": {
        "username": (
            "user_permissions: a pessoa, por login, nome completo, parte do nome, e-mail ou "
            "DN."),
    },
    "ad_move_organizational_unit_parent": {
        "ou_dn": (
            "OU a mover (forma antiga). Para mover usuário, computador ou grupo use "
            "object_name. Aceita nome, caminho ou DN."),
    },
}

ENUMS_DE_LISTA: Dict[str, list] = {
    "object_types": ["user", "group", "computer", "organizationalUnit"],
}

ENUMS_PARAMETROS: Dict[str, list] = {
    "group_scope": ["Global", "DomainLocal", "Universal"],
    "group_type": ["Security", "Distribution"],
    "object_type": ["user", "computer", "group", "organizational_unit"],
}

INSTRUCOES_DO_SERVIDOR = (
    "MCP de Active Directory da Skills IT. 10 tools: para cada tipo de objeto uma de CONSULTA "
    "(ad_search_*) e uma de ALTERACAO (ad_manage_* com 'action'). Usuarios: "
    "ad_search_directory_users / ad_manage_directory_users; grupos: ad_search_directory_groups / "
    "ad_manage_directory_groups; computadores: ad_search_directory_computers / "
    "ad_manage_directory_computers; OUs: ad_search_organizational_units / "
    "ad_manage_organizational_units; seguranca: ad_search_security_reports; servidores e teste "
    "de conexao: ad_search_directory_servers. "
    "Identificadores sao resolvidos pelo servidor: login, nome completo, palavras do nome em "
    "qualquer ordem, e-mail, caminho de OU (Filial/TI) ou DN, sem diferenciar acento. Nunca "
    "peca o login ao usuario so para chamar uma tool. Escrita so executa com identificador "
    "exato ou quando um unico objeto contem todas as palavras informadas como palavras "
    "inteiras; abreviacao, inicial, trecho, erro de digitacao, homonimo ou nome ambiguo "
    "devolvem 'candidatos' sem executar - confirme com o usuario. Toda resposta resolvida traz "
    "'identificacao' com o objeto usado. Em modo multi-AD, consultas aceitam ad_server='todos'; "
    "escritas exigem um unico ad_server, que aceita o nome do cliente (nao precisa consultar "
    "antes). FLUXOS DE UMA CHAMADA: ficha com grupos, grupo primario e OU = "
    "ad_search_directory_users com username; admissao copiando grupos e OU de um colega = "
    "ad_manage_directory_users action=create com copy_from_user (troca de senha no 1o logon ja "
    "e o padrao); numa substituicao, crie a conta nova ANTES de desligar a antiga; desligamento "
    "= action=disable com move_to_ou (e remove_from_groups se pedido); varios grupos = "
    "ad_manage_directory_groups action=add_members com lista. As escritas devolvem o estado "
    "relido do AD: nao consulte de novo para conferir."
)


def descricao_do_parametro(tool_name: str, parametro: str) -> str:
    especifica = DESCRICOES_PARAMETROS_POR_TOOL.get(tool_name, {}).get(parametro)
    return especifica or DESCRICOES_PARAMETROS.get(parametro, "")


def aplicar_descricoes(tool_name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    """Write the single-source parameter texts and enums into a JSON schema.

    Parameters owned by the transport layer (ad_server) keep their own text.
    """
    propriedades = schema.get("properties") or {}
    for nome, spec in propriedades.items():
        if nome == "ad_server" or not isinstance(spec, dict):
            continue
        texto = descricao_do_parametro(tool_name, nome)
        if texto:
            spec["description"] = texto
        if nome in ENUMS_PARAMETROS:
            spec["enum"] = list(ENUMS_PARAMETROS[nome])
        if nome in ENUMS_DE_LISTA:
            itens = {"type": "string", "enum": list(ENUMS_DE_LISTA[nome])}
            for alternativa in [spec] + list(spec.get("anyOf") or []):
                if isinstance(alternativa, dict) and alternativa.get("type") == "array":
                    alternativa["items"] = dict(itens)
    return schema
