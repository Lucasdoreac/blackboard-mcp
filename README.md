# Blackboard MCP

> Local access to Blackboard Ultra for any MCP-compatible client: reads freely,
> writes only your assignment submission, and only when you say so.

Deixa um assistente de IA (Claude, Codex ou outro que fale MCP) **ler o seu
Blackboard** — disciplinas, materiais, atividades, prazos e avisos — para
você perguntar coisas como *"quais atividades vencem esta semana?"* ou
*"resume o aviso novo de Cálculo"*.

- **Lê tudo, escreve uma coisa só.** A única escrita é `submit_assignment`:
  entregar uma atividade. Ela é **inerte por padrão** — sem `confirm=true` ela
  não manda nada, só mostra o que faria e quantas tentativas restam. Nunca abre
  tentativa de prova, nunca muda nota, nunca apaga nada.
  Todo o resto do projeto continua sendo leitura, e isso é garantido por teste:
  a sessão de leitura não tem método de escrita, que vive numa classe separada
  (`submitting.SubmissionWriter`).
- **Roda no seu computador.** Seu login fica numa pasta só sua; senha, código
  de verificação e cookies nunca são mostrados nem enviados a ninguém.
- **Nasceu para a UDF** (é o Blackboard que vem configurado por padrão) e
  **serve qualquer faculdade com Blackboard Ultra** — o `setup` pergunta o
  endereço da sua.
- **Sem telemetria.** Não há conta Blackboard MCP, servidor central nem envio
  de cookies para o projeto.

> **O que é MCP?** É o jeito padrão de ligar uma ferramenta a um assistente de
> IA. Você instala o Blackboard MCP uma vez e avisa o assistente que ele existe
> — daí em diante o assistente consulta o Blackboard sozinho quando precisa.

---

## Antes de começar

Você precisa de:

| O quê | Por quê |
|---|---|
| **macOS ou Linux** | O Windows ainda não é suportado. |
| **Google Chrome** instalado | É por ele que você faz login no Blackboard. |
| **Um assistente com MCP** | Claude Desktop, Claude Code, Codex… |
| Uns **15 minutos** | Na primeira vez. |

Todos os comandos abaixo são digitados no **Terminal** (no Mac: abra o
*Spotlight* com `⌘ + espaço`, digite `Terminal` e aperte Enter). Copie uma
linha por vez, cole no Terminal e aperte Enter.

---

## Passo 1 — Instalar o `uv`

O `uv` baixa e prepara tudo o que o programa precisa (inclusive o Python).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Feche o Terminal e abra de novo** para ele reconhecer o `uv`. Para conferir:

```bash
uv --version
```

Se aparecer um número de versão, deu certo.

## Passo 2 — Baixar o Blackboard MCP

```bash
git clone https://github.com/Lucasdoreac/blackboard-mcp.git ~/blackboard-mcp
```

> **Distribuição:** hoje a instalação é pelo código-fonte. A publicação no
> PyPI será adicionada quando houver uma primeira release estável; não execute
> instaladores de terceiros com o mesmo nome.

> No Mac, se aparecer uma janela pedindo para instalar as "ferramentas de linha
> de comando", aceite, espere terminar e rode o comando de novo.

## Passo 3 — Configurar e fazer login

```bash
cd ~/blackboard-mcp
uv run blackboard-mcp setup
```

O projeto já vem apontado para a UDF; o `setup` grava a faculdade do SEU perfil
e é o que impede alguém de ser direcionado por engano à instituição de outra
pessoa. Rode-o mesmo sendo da UDF — é ele que faz o login.

Na primeira vez demora um pouco (está instalando as dependências). Depois ele
pergunta duas coisas:

1. **O endereço do Blackboard da sua faculdade.** Abra o Blackboard no
   navegador e copie só o começo do endereço — por exemplo
   `https://bb.suafaculdade.edu.br`. Na UDF é
   `https://bb.cruzeirodosulvirtual.com.br` (o padrão do projeto).
2. **Um nome para o seu perfil.** Digite uma palavra simples, como o seu
   primeiro nome (`maria`). **Anote:** você vai usar esse nome nos próximos
   passos.

Em seguida abre uma janela do Chrome. **Faça login normalmente** (e o código de
verificação, se a faculdade pedir). O Terminal percebe sozinho quando o login
termina e mostra *"Login confirmado"*. Pode fechar essa janela do Chrome.

## Passo 4 — Conferir

Troque `maria` pelo nome que você escolheu:

```bash
uv run blackboard-mcp courses --profile maria
```

Deve aparecer a lista das suas disciplinas. Se apareceu, está tudo pronto do
lado do Blackboard.

## Passo 5 — Ligar ao seu assistente

Descubra o caminho completo do `uv` (vai ser usado abaixo):

```bash
which uv
```

Vai aparecer algo como `/Users/maria/.local/bin/uv`. Nos exemplos, troque:
- `CAMINHO_DO_UV` pelo que o `which uv` mostrou;
- `SEU_USUARIO` pelo seu usuário do computador (a parte depois de `/Users/` ou
  `/home/` no caminho acima);
- `maria` pelo nome do seu perfil.

### Claude Desktop

1. Abra o Claude Desktop → **Settings** → **Developer** → **Edit Config**.
2. O arquivo `claude_desktop_config.json` abre. Deixe-o assim (se já houver
   outros servidores em `mcpServers`, só acrescente o bloco `blackboard`):

```json
{
  "mcpServers": {
    "blackboard": {
      "command": "CAMINHO_DO_UV",
      "args": [
        "--directory", "/Users/SEU_USUARIO/blackboard-mcp",
        "run", "blackboard-mcp", "serve", "--profile", "maria"
      ]
    }
  }
}
```

No Linux, o caminho da pasta é `/home/SEU_USUARIO/blackboard-mcp`.

3. Salve, **feche o Claude Desktop por completo e abra de novo**.

> Por que o caminho completo do `uv`? Aplicativos abertos pelo Dock não
> enxergam os programas que o Terminal enxerga; com `uv` sozinho, o Claude
> Desktop não acha o programa.

### Claude Code

Um comando no Terminal:

```bash
claude mcp add blackboard -- uv --directory ~/blackboard-mcp run blackboard-mcp serve --profile maria
```

### Outros assistentes (Codex etc.)

Todo cliente MCP pede as mesmas duas coisas: o **comando** (`CAMINHO_DO_UV`) e
os **argumentos**
(`--directory /Users/SEU_USUARIO/blackboard-mcp run blackboard-mcp serve --profile maria`).

## Pronto — experimente

Pergunte ao assistente, por exemplo:

- *"Quais disciplinas eu tenho no Blackboard?"*
- *"Que atividades têm prazo nos próximos dias?"*
- *"Tem aviso novo em alguma disciplina?"*
- *"O que pede o enunciado da atividade 3 de Estruturas de Dados?"*

---

## Quando algo dá errado

| Aconteceu | O que fazer |
|---|---|
| `uv: command not found` | Feche e abra o Terminal de novo. Se continuar, repita o Passo 1. |
| O assistente diz que precisa de login, ou a sessão expirou | A sessão do Blackboard vence de tempos em tempos. Rode `cd ~/blackboard-mcp && uv run blackboard-mcp login --profile maria` e faça login de novo. |
| `courses` mostra a lista vazia ou falta disciplina | Algumas disciplinas não aparecem como cartão no Blackboard. Veja "Disciplina que não aparece" abaixo. |
| O Chrome não abre | Confira se o **Google Chrome** está instalado. Se ele estiver num lugar diferente do normal, informe o caminho antes do comando: `export BLACKBOARD_CHROME_PATH="/caminho/do/chrome"`. |
| O assistente não mostra o Blackboard | Confira o caminho do `uv` e da pasta no arquivo de configuração e reinicie o assistente por completo. |
| O login da faculdade bloqueia o navegador | Algumas instituições barram login por navegador controlado por programa; nesse caso não há como contornar por aqui. |

Antes de abrir uma issue, rode este diagnóstico local (não abre Chrome, não
chama o Blackboard e não imprime cookies):

```bash
uv run blackboard-mcp doctor --profile maria
```

### Disciplina que não aparece

Se você acessa a disciplina pelo navegador mas ela não vem na lista, registre-a
uma vez. O código da disciplina está no endereço dela no Blackboard — a parte
parecida com `_1169577_1`:

```bash
uv run blackboard-mcp register-course --profile maria --course-id _1169577_1 --title "Nome da disciplina"
```

### Sou de outra faculdade

Nada a editar: o `setup` grava o endereço por perfil e
`BLACKBOARD_BASE_URL` vence tudo (bom para scripts). Se você clonou o projeto
para a sua instituição e quer que ele já venha configurado, troque só
`DEFAULT_BASE_URL` em `src/blackboard_mcp/config.py` — é o único lugar do
código que conhece a instituição.

### Atualizar para a versão mais nova

```bash
cd ~/blackboard-mcp && git pull
```

---

## O que o assistente consegue fazer

| Ferramenta | Para quê |
|---|---|
| `auth_status`, `reauthenticate` | Ver se o login vale e renovar a sessão |
| `list_terms`, `list_courses` | Semestres e disciplinas |
| `register_course`, `list_registered_courses`, `sync_registered_courses` | Disciplinas que o Blackboard esconde dos cartões |
| `list_course_content`, `list_course_tree`, `sync_course`, `sync_available_courses` | Estrutura de pastas e materiais (sem abrir nada) |
| `list_assessments`, `list_course_activities`, `get_assessment` | Atividades, prazos e enunciados — com o link para abrir no Blackboard |
| `list_answered_assessments` | Questões de avaliações já respondidas, com gabarito quando o professor liberou |
| `read_open_attempt` | Questões de uma tentativa que **você** já abriu (nunca abre uma) |
| `read_assessment_attachment` | Imagens do enunciado |
| `list_announcements` | Avisos dos professores — com o link |
| `list_course_documents`, `list_video_descriptions`, `list_video_transcripts` | Texto das páginas, descrições e legendas das videoaulas |
| `download_content`, `archive_declared_pdfs`, `list_downloads`, `read_download_chunk` | Baixar materiais pedidos para uma pasta privada no seu computador |

## Privacidade e segurança

- Tudo fica em `~/.local/share/blackboard-mcp/`, com permissão só para o seu
  usuário. O perfil é pessoal — não compartilhe essa pasta.
- Senha, código de verificação, cookies e links temporários de download nunca
  aparecem na tela, nas respostas ao assistente nem em arquivos do projeto.
- O acesso é feito pelo próprio navegador logado, como se fosse você navegando.
  Nada é escrito no Blackboard.
- Os materiais baixados ficam no seu computador; o que o assistente faz com as
  respostas depende do assistente que você usa.
- **Use só com a sua própria conta**, dentro das regras da sua instituição. O
  Blackboard MCP não contorna login, verificação em duas etapas nem permissão:
  ele vê exatamente o que você veria no navegador.
- `serve` (stdio) é o modo recomendado para assistentes locais. `serve-http`
  existe apenas para uma bridge local por socket Unix autenticado; ele não deve
  ser exposto na rede.

## Documentação

- [Arquitetura](docs/ARCHITECTURE.md) — limites entre navegador, REST e MCP.
- [Segurança](SECURITY.md) — escopo, sessões e relato de vulnerabilidades.
- [Contribuição](CONTRIBUTING.md) — ambiente, testes e regras de compatibilidade.
- [Integração opcional com Sober](docs/SOBER.md) — não é requisito do MCP.

## Licença

[MIT](LICENSE). Use, modifique e redistribua; mantenha o aviso de copyright.

## Para quem vai programar

- Testes: `uv run --frozen pytest -q`
- Comandos avulsos (sem perguntas interativas, bom para scripts): `login`,
  `auth-status`, `courses`, `tree`, `assessments`, `sync`, `download`… — veja
  `uv run blackboard-mcp --help`. `BLACKBOARD_BASE_URL` substitui o endereço
  salvo pelo `setup`, e `BLACKBOARD_MCP_HOME` troca a pasta de dados.
- Decisões de desenho: [`docs/DECISIONS.md`](docs/DECISIONS.md). Integração com
  o SOBER: [`docs/SOBER.md`](docs/SOBER.md).
