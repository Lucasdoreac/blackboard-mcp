# Contribuindo

## Ambiente

```bash
uv sync --all-groups
uv run --frozen pytest -q
```

Antes de abrir um pull request, rode a suíte completa e mantenha as mudanças
independentes de uma instituição específica. Não adicione URLs reais de alunos,
cookies, IDs de cursos, materiais acadêmicos ou perfis de navegador ao repo.

## Contrato do projeto

- Leituras devem continuar somente leitura: nunca iniciar tentativa, enviar
  resposta ou modificar conteúdo do Blackboard.
- O Chrome serve para autenticação; dados de curso devem preferir endpoints
  REST autenticados quando existirem.
- O transporte stdio não pode escrever logs em stdout.
- Integrações como Sober pertencem a documentação ou adaptadores opcionais;
  não podem virar dependência do núcleo.

## Releases

Use versionamento semântico. Uma release deve executar testes, construir o
wheel em ambiente limpo e documentar mudanças de compatibilidade ou permissões.
