# Usar com o SOBER

Só interessa a quem roda o SOBER. Quem usa o Blackboard MCP sozinho pode ignorar este arquivo.

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
