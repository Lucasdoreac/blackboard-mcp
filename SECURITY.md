# Política de segurança

## Escopo

O projeto guarda cookies de sessão localmente e acessa dados acadêmicos do
usuário. Nunca inclua cookies, senhas, códigos MFA, capturas de tela com dados
pessoais ou URLs temporárias em issues, logs ou pull requests.

## Relatar uma vulnerabilidade

Use uma GitHub Security Advisory privada neste repositório. Se ela não estiver
habilitada, abra uma issue mínima pedindo um canal privado e não descreva a
vulnerabilidade publicamente. Inclua versão, sistema operacional, impacto e
passos de reprodução sem credenciais.

## Operação segura

- Prefira `serve` por stdio em clientes locais.
- Não exponha `serve-http` em TCP ou na internet.
- Mantenha `BLACKBOARD_MCP_HOME` privado e não o sincronize em nuvens públicas.
- Atualize a ferramenta e refaça o login após suspeita de vazamento da sessão.
