#!/usr/bin/env bash
# Login no Mac (onde o Chrome do dono já tem SSO/MFA) e envio do session.json
# ao host da bridge. A bridge relê o arquivo na próxima rejeição (auth_status,
# keep-alive ou qualquer leitura) — não precisa de restart.
#
# Uso, de dentro do checkout do blackboard-mcp no Mac:
#   ops/login-remote.sh [--host ubuntu] [--profile sober] [--skip-login]
#
# Destino fixo por perfil: ~/.local/share/blackboard-mcp/profiles/<perfil>/session.json
# no host remoto. O arquivo chega por um único `ssh` com umask 077, é gravado
# num temporário no MESMO diretório, recebe chmod 600 e só então troca de nome
# (mv atômico): a bridge nunca lê um session.json pela metade nem com modo
# aberto. Nenhum valor de cookie é impresso.
set -euo pipefail

host="${BLACKBOARD_BRIDGE_HOST:-ubuntu}"
profile="sober"
skip_login=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host) host="$2"; shift 2 ;;
    --profile) profile="$2"; shift 2 ;;
    --skip-login) skip_login=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "login-remote: argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

# Mesmo formato aceito por Settings.from_profile; também impede que o nome do
# perfil injete algo no comando remoto.
if ! [[ "$profile" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ ]]; then
  echo "login-remote: perfil invalido: $profile" >&2
  exit 2
fi
if ! [[ "$host" =~ ^[a-zA-Z0-9._@-]+$ ]]; then
  echo "login-remote: host invalido: $host" >&2
  exit 2
fi

data_home="${BLACKBOARD_MCP_HOME:-$HOME/.local/share/blackboard-mcp}"
src="$data_home/profiles/$profile/session.json"

if [ "$skip_login" -eq 0 ]; then
  uv run blackboard-mcp login --profile "$profile"
fi
if [ ! -s "$src" ]; then
  echo "login-remote: $src nao existe; rode o login primeiro" >&2
  exit 1
fi

remote_dir=".local/share/blackboard-mcp/profiles/$profile"
ssh "$host" "umask 077 && cd && mkdir -p '$remote_dir' && chmod 700 '$remote_dir' \
  && tmp=\$(mktemp '$remote_dir/session.json.XXXXXX') \
  && cat > \"\$tmp\" && chmod 600 \"\$tmp\" && mv -f \"\$tmp\" '$remote_dir/session.json'" < "$src"

echo "session.json do perfil '$profile' enviado para $host:~/$remote_dir/session.json (modo 600)."
echo "A bridge usa o cookie novo na proxima chamada; confira com a tool auth_status."
