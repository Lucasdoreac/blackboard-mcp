# Decisões de produto

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
