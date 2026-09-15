# Arquitetura

O Blackboard MCP é uma ferramenta local e de somente leitura. Não depende de
Sober, WAHA, Docker, NotebookLM ou qualquer serviço do mantenedor.

```text
Cliente MCP (Codex, Claude, outro)
              │ stdio (padrão)
       blackboard-mcp
          ├── Playwright + Chrome: login e MFA
          └── httpx: GETs autenticados em /learn/api/v1
                       │
                 Blackboard Ultra
```

## Sessão

O login é interativo no Chrome. Depois de comprovada uma chamada a
`/learn/api/v1/users/me`, a sessão é guardada com permissões do usuário em
`~/.local/share/blackboard-mcp/profiles/<perfil>/session.json`. As leituras
seguintes reutilizam essa sessão por HTTPS; o navegador não é usado para cada
consulta.

## Transportes

- `serve`: MCP por stdio. É o modo padrão e mais compatível; stdout contém
  somente mensagens MCP.
- `serve-http`: bridge por socket Unix local, autenticada por chave de ambiente.
  É destinada a integrações locais, como Sober, e não é uma API pública.

## Limites de segurança

As ferramentas não iniciam tentativas, enviam respostas, entregam atividades
nem modificam o Blackboard. `read_open_attempt` só lê uma tentativa que o
próprio aluno já abriu. URLs e anexos são restringidos ao host e às rotas
autorizadas do Blackboard.
