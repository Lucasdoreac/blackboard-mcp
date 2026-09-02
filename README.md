# Blackboard MCP

Servidor MCP local e somente leitura para Blackboard Ultra. Ele e um produto
independente: Codex, Claude Desktop e SOBER podem ser clientes do mesmo
servidor, mas a sessao nunca entra no repositorio do SOBER.

## Primeiro uso

Funciona com **qualquer instituicao que rode Blackboard Ultra**, nao so a do
piloto original. Depois de instalar Python/uv (o unico passo tecnico), o
resto e guiado:

```bash
cd ~/dev/blackboard-mcp
uv run blackboard-mcp setup
```

O assistente pergunta a URL do Blackboard da sua instituicao e um nome pro
seu perfil, salva essa configuracao localmente (nunca precisa editar `.env`
nem codigo), abre um Chrome dedicado pra voce fazer login e MFA, e confirma
sozinho quando o login terminar. O perfil fica em
`~/.local/share/blackboard-mcp/profiles/<nome>`, com permissoes restritas.
Senhas, codigos MFA, cookies e URLs assinadas nunca sao impressos, retornados
por MCP ou versionados.

Depois do `setup`, ou pra scripting/CI (sem prompt interativo), os comandos
individuais continuam disponiveis:

```bash
uv run blackboard-mcp login --profile <nome>          # so o login, sem os prompts
uv run blackboard-mcp auth-status --profile <nome>
uv run blackboard-mcp courses --profile <nome>
```

Automacao/CI tambem pode pular o `setup` de vez e so exportar
`BLACKBOARD_BASE_URL` (tem prioridade sobre a config salva pelo `setup`).

Algumas disciplinas permanecem acessiveis mas o Ultra nao as exibe como
cartoes abertos. Registre-as uma vez para que todo cliente MCP tenha o mesmo
catalogo local:

```bash
uv run blackboard-mcp register-course --profile <nome> \
  --course-id _1169577_1 --title "Linguagens Formais e Autômatos"
uv run blackboard-mcp sync-registered --profile <nome>
```

## MCP

No cliente MCP, execute:

```json
{
  "command": "uv",
  "args": ["--directory", "/home/ludoc/dev/blackboard-mcp", "run", "blackboard-mcp", "serve", "--profile", "sober"]
}
```

Ferramentas: `auth_status`, `begin_login`, `list_courses`, `list_terms`,
`register_course`, `list_registered_courses`, `bind_notebook`,
`sync_registered_courses`, `sync_available_courses`, `list_course_content`,
`list_course_tree`, `sync_course`, `list_assessments`, `list_announcements`,
`download_content`, `archive_declared_pdfs`, `list_downloads` e
`read_download_chunk`. A arvore expande apenas modulos/pastas;
nao abre materiais. Elas leem a interface Ultra autenticada, pois a API publica de
desenvolvedor requer uma credencial institucional separada. Elas nao escrevem
no Blackboard. `download_content` so baixa um item explicitamente solicitado,
para `~/.local/share/blackboard-mcp/downloads/`, com permissao privada, hash e
recibo. A URL assinada que Blackboard gera nunca sai do navegador nem entra no
recibo. A ponte Blackboard -> NotebookLM continua sendo responsabilidade do
cliente (SOBER, Codex ou Claude), nao deste servidor de leitura.

`archive_declared_pdfs` e o equivalente CLI `archive-pdfs` baixam somente itens
cujo titulo do inventario declara explicitamente um PDF. A operacao e
idempotente: recibos cujo hash ainda confere sao pulados. Videoaulas, paginas,
links externos e streaming ficam inventariados, mas nao sao abertos nem
extraidos por essa ferramenta; cada formato precisa de uma integracao que
respeite a forma oficial de acesso e qualquer DRM.

## Bridge para SOBER

O container SOBER nao pode controlar o Chrome do host. A ponte prevista e MCP
Streamable HTTP por socket Unix, nunca por uma porta exposta na rede:

Instale a unidade de usuário a partir de
`ops/systemd/blackboard-mcp-bridge.service.example` e crie o arquivo privado
`~/.config/blackboard-mcp/bridge.env` a partir de `bridge.env.example`.
Ela usa `%t/blackboard-mcp/bridge.sock` (normalmente
`/run/user/<uid>/blackboard-mcp/bridge.sock`), sem expor porta TCP.

O cliente no container envia a mesma chave no cabecalho
`x-sober-bridge-key`; o socket e montado somente no `api`. Configure o
diretório do socket em `BLACKBOARD_MCP_SOCKET_DIR` e a chave em
`BLACKBOARD_MCP_BRIDGE_KEY` no `.env` privado do SOBER, além de
`BLACKBOARD_MCP_ENABLED=true`.

## Limites de seguranca

- O perfil pertence ao usuario local; nao e compartilhado entre pessoas.
- O host Blackboard e configuravel por perfil (`blackboard-mcp setup`, ou a
  variavel `BLACKBOARD_BASE_URL`) — funciona com qualquer instituicao Ultra,
  desde que ela nao bloqueie login por navegador automatizado.
- A API e chamada dentro do contexto autenticado do navegador. Isso evita
  copiar cookies para MCP, banco ou logs.
- A resposta de ferramentas e sanitizada: nao devolve headers, cookies ou URL
  de download temporaria.
