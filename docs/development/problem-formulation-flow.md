# Fluxo local de formulação de problemas públicos

Esta primeira fase do ObservAInova entrega uma jornada completa: a pessoa descreve
um problema público, explicita seu contexto em oito perguntas, revisa a formulação
sem paráfrases automáticas e confirma uma versão imutável. O sistema termina em um
encaminhamento seguro para o futuro mapa de contribuições científicas.

## Iniciar o ambiente

Na raiz do repositório, execute:

```bash
docker compose -f infra/compose.yaml up --build
```

Quando os serviços estiverem saudáveis, use:

- aplicação pública: <http://localhost:3000>;
- documentação da API: <http://localhost:8000/docs>.

Em uma base nova, ou depois de receber uma migração, aplique o esquema antes de
usar o fluxo:

```bash
cd apps/api && uv run alembic upgrade head
```

Se a API estiver sendo executada apenas no contêiner, o equivalente é:

```bash
docker compose -f infra/compose.yaml exec api alembic upgrade head
```

## O que a jornada registra

A descrição livre abre o rascunho. Em seguida, o assistente pergunta, nesta ordem:

1. `territory` — território ou unidade administrativa;
2. `affected_population_or_service` — população, serviço ou organização afetada;
3. `observed_consequences` — consequências observadas;
4. `perceived_causes` — causas percebidas;
5. `attempted_actions` — ações já tentadas e seus resultados;
6. `available_resources` — recursos e capacidades disponíveis;
7. `constraints` — restrições que precisam ser respeitadas;
8. `desired_outcome` — resultado concreto desejado.

“Não sei informar” é uma resposta válida. O valor fica ausente e recebe o estado
`unknown`; a plataforma não completa a lacuna. Causas declaradas são registradas
como `perception`, nunca como fato verificado. Antes da confirmação, a pessoa vê
todo o conteúdo exatamente como informou.

## Limite de privacidade e recuperação

Cada rascunho é privado. Na criação, a API devolve uma única vez um token bruto de
edição. A aplicação o guarda somente em `sessionStorage` e o envia no cabeçalho
`X-Problem-Token` em leituras e alterações. A URL, o HTML e os registros persistidos
não contêm esse token; o banco armazena apenas seu resumo criptográfico SHA-256.

Nesta fase não há conta de usuário nem recuperação do token. Fechar a sessão do
navegador ou perder o token torna o rascunho privado irrecuperável. Isso é uma
fronteira de segurança deliberada do primeiro recorte, não uma promessa de
recuperação futura.

## O que acontece depois da confirmação

A confirmação cria uma versão imutável do contexto aprovado e apresenta o estado
`awaiting_validated_contributions`. Esse estado significa que o problema está apto
a receber relações com teses e dissertações, mas ainda não possui um mapa de
caminhos publicável.

O subsistema de contribuições científicas validadas e o mapa de caminhos são
projetos separados. Eles exigirão trechos-fonte, revisão humana, proveniência,
barreiras, condições de aplicação e governança próprias. Até que existam
contribuições validadas, a interface não inventa recomendações nem apresenta uma
saída automática como evidência científica.

## Verificações

Os testes locais, a tipagem e a compilação podem ser executados com:

```bash
make check
```

Com a API e a aplicação em execução, valide a jornada completa no navegador:

```bash
cd apps/web && npx playwright install chromium && cd ../..
make e2e
```

A instalação do Chromium é necessária somente na primeira execução ou quando a
versão do Playwright mudar.

## Parar e retomar sem perder dados

Para interromper os contêineres mantendo-os prontos para retomada:

```bash
docker compose -f infra/compose.yaml stop
```

Para remover os contêineres e a rede sem apagar os volumes persistentes:

```bash
docker compose -f infra/compose.yaml down
```

Não acrescente `--volumes` ou `-v` se quiser preservar PostgreSQL e MinIO.
