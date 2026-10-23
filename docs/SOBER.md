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

## Sessão: keep-alive, aviso e login remoto

A bridge renova a janela de inatividade de 8 h do cookie `BbRouter` a cada
20 min. Depois de uma falha, re-tenta a cada 5 min até voltar a funcionar.
Cada falha vai para o journal da unidade
(`journalctl --user -u blackboard-mcp-bridge`) com a classe (`network`,
`session_stale`, `rejected`) e o tempo restante da sessão. O valor do cookie
nunca aparece no log.

A tool `auth_status` devolve, além de `authenticated`:

| campo | significado |
|---|---|
| `expires_at` | fim da janela de inatividade do cookie atual (unix ts) |
| `last_keepalive_ok_at` | último ping bem-sucedido (unix ts; `null` antes do primeiro) |
| `keepalive_failing` | `true` quando os pings estão falhando **e** restam menos de 2 h |
| `keepalive_consecutive_failures`, `last_keepalive_failure_class` | diagnóstico |

`keepalive_failing: true` significa que o dono precisa logar antes que a sessão
vença. Se o login for feito em outro computador, envie a sessão ao host da
bridge. No checkout do blackboard-mcp no Mac:

```sh
ops/login-remote.sh --host ubuntu --profile sober
```

O script roda `blackboard-mcp login` no Mac e grava o `session.json` em
`~/.local/share/blackboard-mcp/profiles/<perfil>/` no host com modo 600
(troca atômica). A bridge relê o arquivo na próxima chamada recusada,
`auth_status` inclusive, então o serviço não precisa ser reiniciado. Use
`--skip-login` para só reenviar uma sessão já gravada.
