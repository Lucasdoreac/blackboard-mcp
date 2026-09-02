# Plano: estudos via Blackboard, SOBER e NotebookLM

## Resultado de produto

No self-chat do dono, o SOBER deve responder a perguntas como:

```text
/estudos pendencias
```

com tarefas abertas, prazo, disciplina, link original e uma sugestao de proxima
acao. Para uma disciplina, por exemplo:

```text
/estudos atualizar big-data
```

ele deve inventariar o material novo, baixar somente recursos permitidos,
atualizar o caderno NotebookLM correspondente quando solicitado e devolver um
resumo verificavel. A consulta livre do material continua em `/nb <alias>
perguntar ...`, respondida pelo NotebookLM/Gemini; Groq apenas interpreta
conversa e nunca recebe o catalogo inteiro de tools ou material academico.

## Limites

- Dono/self-chat somente na primeira versao. Nenhuma mensagem a professor,
  colega, grupo ou conta externa.
- Blackboard: leitura, inventario e download. Nunca enviar atividade,
  responder prova, alterar nota, marcar presenca ou abrir conteudo apenas para
  produzir progresso artificial.
- NotebookLM: criar/alterar caderno e fontes somente por comando explicito do
  dono ou politica de sincronizacao previamente confirmada por disciplina.
- GitHub: descobrir e resumir repositorios vinculados; criar issue, commit ou
  push exige o fluxo HITL existente do maintainer.
- Nunca guardar senha, MFA, cookie, URL assinada de download ou dados de
  terceiros em Postgres, logs ou WhatsApp.

## Arquitetura alvo

```text
Chrome perfil sober (host Ubuntu)
            │ CDP somente em 127.0.0.1
            ▼
blackboard-mcp (host; leitura Ultra; estado local)
            │ MCP Streamable HTTP autenticado por socket/credencial local
            ▼
adaptador Blackboard do SOBER (container)
            ├─ Postgres: cursos, itens, snapshots, pendencias, vinculos
            ├─ disco: downloads hashados e manifestos
            ├─ NotebookLM MCP: caderno/fonte por disciplina
            ├─ GitHub: somente leitura e resumo de repos vinculados
            └─ WAHA: resposta ao self-chat e envio de documento permitido
```

O host e o container nao compartilham o perfil Chrome nem cookies. O bridge MCP
deve ser uma conexao autenticada localmente; nao expor a porta CDP ou o servidor
Blackboard na rede LAN/VPS.

## Fases e criterios de aceite

### E1 — Blackboard MCP de leitura confiavel

1. Manter `auth_status`, `begin_login`, `list_courses`,
   `list_course_content` (ja validados no perfil `sober`).
2. Acrescentar recursao de pastas, itens avaliativos, prazos, anexos, documentos
   incorporados e videoaulas, sem clicar em recursos que mudam progresso.
3. Resolver URLs assinadas somente no momento do download; persistir apenas
   `course_id`, `content_id`, hash, tamanho, MIME, titulo e data de observacao.
4. `sync_delta` produz manifestos deterministas e nao baixa novamente o mesmo
   hash.

Aceite: Big Data produz um manifesto completo de unidades, PDFs, videoaulas e
avaliacoes; uma segunda sync nao baixa nada sem mudanca.

### E2 — Ponte host → SOBER

1. Executar o servidor Blackboard no host, com perfil e CDP locais.
2. Estender `MCPClient` do SOBER para Streamable HTTP autenticado, sem forcar o
   subprocesso Docker a acessar o Chrome do host.
3. Criar gate `BLACKBOARD_MCP_ENABLED=false` por padrao, URL local e segredo de
   bridge fora do repositorio. Falha de login vira `auth_required`, nunca retry
   de senha ou exposicao de erro cru.
4. Adicionar health/status no control plane e aviso apenas no self-chat quando
   a autenticacao ou sync precisar de atencao.

Aceite: SOBER chama `auth_status` e `list_courses` pelo bridge; perfil expirado
gera aviso acionavel no self-chat e nenhum dado sai para grupos.

### E3 — Dominio academico no SOBER

Tabelas aditivas: `study_courses`, `study_content_items`, `study_snapshots`,
`study_tasks`, `study_artifacts`, `study_notebook_bindings`,
`study_repo_bindings` e `study_sync_runs`.

- Chaves externas: host Blackboard, `course_id` e `content_id`.
- Snapshot permite diferenciar novo, alterado, removido e inacessivel.
- Tarefa tem origem, prazo, status observado e `requires_owner_review`; nao
  infere que uma atividade foi entregue.
- Artefato local tem hash e permissao de entrega no WhatsApp.

Aceite: uma sync gera um diff persistido; `/estudos pendencias` funciona mesmo
se Blackboard estiver temporariamente indisponivel, marcando a leitura como
desatualizada.

### E4 — Comandos deterministas do self-chat

```text
/estudos status
/estudos atualizar [alias]
/estudos pendencias [alias]
/estudos material <alias> [novo|todos]
/estudos baixar <item_id>
/estudos caderno criar <alias> confirmar
/estudos caderno sincronizar <alias> confirmar
/estudos repo vincular <alias> <github-owner/repo> confirmar
/estudos plano <alias> <tarefa_id>
```

`atualizar`, `pendencias`, `status` e `material` sao leitura. `baixar` entrega
somente artefato permitido ao self-chat. Criar/atualizar NotebookLM e vincular
repo usam confirmacao porque produzem efeito externo ou configuracao duravel.

Aceite: Groq nao recebe schemas Blackboard/NotebookLM no chat livre. Os
comandos acima chamam adaptadores deterministas; cada resposta inclui origem e
momento da ultima sync.

### E5 — NotebookLM e plano de trabalho

Para cada disciplina, o owner pode criar um alias NotebookLM vinculado ao
curso. A sync envia fontes com titulo/metadata de origem e hash, sem duplicar.
O resumo de uma tarefa combina fatos do Blackboard com perguntas ao caderno.

Para uma atividade de analise de requisitos, `/estudos plano <alias> <tarefa>`:

1. mostra enunciado, prazo e fontes usadas;
2. busca o repo apenas se houver `study_repo_binding` confirmado;
3. produz proposta, checklist e perguntas abertas;
4. nunca escreve no repositorio sem um comando maintainer/HITL separado.

Aceite: o plano declara explicitamente o que veio do Blackboard, NotebookLM e
GitHub e o que ainda precisa de decisao do dono.

### E6 — Automacao e interface de dono

Depois de sync manual estavel, agendar leitura com janela e limite de taxa.
Notificar apenas diferencas relevantes: tarefa nova, prazo alterado, material
novo, autenticacao expirada ou falha persistente. A nova UI de dono mostra
perfil Blackboard, cursos, ultima sync, pendencias, downloads, cadernos e
vinculos de repositorio; ela reaproveita autenticacao/auditoria do SOBER, nao a
navegacao administrativa legada.

## Ordem imediata

1. Completar E1 para cada formato observado: PDF ja provado; video, texto e
   repositorio externo ainda precisam de tratadores semanticos proprios.
2. Escolher e provar o bridge local seguro de E2 em ambiente Docker, sem abrir
   CDP para a rede.
3. Implementar E3+E4 em um PR pequeno: sync manual, tarefas e `/estudos
   pendencias` para o self-chat.
4. So entao criar/sincronizar NotebookLM por disciplina e vincular repositorios.

## Evidencia atual

Em 2026-08-31, o perfil local `sober` foi autenticado no Blackboard Ultra. O
MCP leu quatro cursos disponiveis e os seis itens-raiz de Big Data. A API
publica de desenvolvedor retornou 403 para a sessao pessoal; o adaptador usa a
interface Ultra autenticada em vez de prometer uma API institucional inexistente
para esse perfil.

O inventario recursivo de Big Data tambem foi validado: ele encontrou as cinco
unidades, seus cinco PDFs e cinco videoaulas, cinco avaliacoes `AS - Unidade`,
Boas-vindas e Cruzeiro Play sem abrir material de folha nem alterar o progresso.
As cinco avaliacoes foram extraidas com prazo `2026-11-06T23:59:00-03:00` e
estado `listed`. Esse estado deliberadamente nao afirma pendencia ou submissao:
a proxima leitura precisa provar tal status antes de o self-chat dizer que algo
esta em aberto.

O filtro de semestre passou a ser explicito. Em `2 Semestre 2026`, quatro
disciplinas foram sincronizadas em manifestos locais: Computabilidade (15
itens), Big Data (34), Computacao Paralela e Distribuida (12) e Estagio (11).
Uma segunda sync de Big Data retornou diff vazio, provando estabilidade do
baseline apos o enriquecimento de metadata.

A ponte E2 tambem foi provada localmente: Streamable HTTP MCP sobre socket Unix
com permissao `0600` e cabecalho autenticado enumerou as quatro ferramentas.
Um container descartavel da imagem real `sober-api:latest`, sem rede, montou o
socket e repetiu a descoberta. A imagem atual usa Python 3.11. Ambos os testes
emitiram um aviso de encerramento do cliente MCP; a comunicacao e descoberta
funcionaram, mas a integracao do SOBER deve cobrir encerramento limpo antes de
habilitar o feature gate.

Em 2026-09-01, a listagem de cartoes do Ultra foi reconhecida como incompleta:
Linguagens Formais e Automatos (`_1169577_1`, 10 itens) e Itinerario
Extensionista 5 (`_1169587_1`, 16 itens) continuam acessiveis mesmo quando nao
aparecem como cartoes abertos. Ambos receberam manifestos privados locais. O
download de PDF foi provado em LFA para a aula inaugural (12 paginas) e o plano
de aulas 2026.2 (3 paginas); cada artefato possui hash e recibo em
`~/.local/share/blackboard-mcp/downloads/`, sem URL assinada. Videoaulas,
Markdown e links GitHub nao sao tratados como PDF e permanecem explicitamente
fora da automacao de download ate que seus contratos sejam implementados.

No NotebookLM, os cadernos existentes de LFA e Computabilidade foram
preservados, e a colecao `UDF — 2026.2` passou a reuni-los com o novo caderno
de Itinerario. Em uma segunda tentativa, Big Data, Computacao Paralela e
Estagio tambem ganharam cadernos; a API recusou a atualizacao unica da colecao
para incluir os tres (`INVALID_ARGUMENT`), sem alterar sua composicao atual.
O vinculo curso→caderno deve ser persistido pelo dominio E3 antes da proxima
tentativa incremental, em vez de depender apenas da colecao visual.
