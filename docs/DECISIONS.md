# Decisões de produto

## 2026-09-15 — Produto público não tem instituição nem perfil do mantenedor

O MCP não traz URL de Blackboard, credenciais ou perfil pré-configurados. O
perfil padrão agora é `default`; `blackboard-mcp setup` escolhe a instituição
e grava a configuração localmente. Uma automação pode usar
`BLACKBOARD_BASE_URL`, que tem precedência sobre a configuração salva.

O perfil chamado `sober` e a ponte para Sober continuam suportados apenas como
integração opcional, documentada em `docs/SOBER.md`. Eles não fazem parte do
caminho de instalação de quem usa o MCP diretamente.

## 2026-09-02 — Setup guiado, sem editar código, pra qualquer instituição

O `README.md` já registrava "o host Blackboard é fixo... neste piloto" como
limite conhecido. `docs/DECISIONS.md` (2026-08-31, abaixo) já registrava a
intenção de ser multi-cliente/multi-instituição desde a origem — faltava o
caminho de configuração pra isso virar realidade sem editar código.

Decisão: `base_url` deixa de ser hardcoded (`login_url()` validava contra
uma string fixa) e passa a resolver em 3 camadas — env var (scripting/CI) →
config persistida por perfil (`~/.local/share/blackboard-mcp/profiles/
<perfil>/config.json`, escrita por `blackboard-mcp setup`). Novo comando `setup`
interativo é o único ponto de entrada esperado pra alguém de outra
instituição: pergunta a URL do Blackboard e um nome de perfil, salva,
abre o Chrome de login e confirma sozinho — zero arquivo pra editar na mão.

Escopo deliberadamente NÃO incluído aqui: setup guiado da ponte systemd
pro Sober. Isso só importa pra quem quer a integração estilo WhatsApp; o
público que esta mudança mira (alguém de outra faculdade usando
`blackboard-mcp serve` direto no Claude Desktop/Codex) não precisa dela.

## 2026-08-31 — Blackboard MCP é independente do SOBER

O Blackboard MCP é instalado fora do repositório e pode atender Codex, Claude
Desktop e SOBER pelo mesmo protocolo MCP. O SOBER não é a origem da sessão nem
o local de armazenamento de credenciais.

O WhatsApp continuará sendo uma superfície rápida do SOBER, mas não é a única
interface pretendida. Uma futura interface de dono deve reaproveitar apenas
autenticação, auditoria, filas e serviços maduros da UI administrativa atual;
ela não deve herdar a navegação e o modelo mental de MSP/tenants/billing.

## 2026-08-31 — Sessão por perfil local

`blackboard-mcp login --profile sober` abre um Chrome persistente dedicado.
O usuário faz login e MFA diretamente no provedor. A sessão fica somente no
perfil local protegido e nunca é copiada para banco, logs, respostas MCP ou
repositório. Expiração retorna uma falha sanitizada e pede reautenticação.
