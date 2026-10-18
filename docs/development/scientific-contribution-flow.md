# Fluxo de contribuições científicas validadas

Esta fase transforma teses e dissertações em contribuições científicas utilizáveis a partir de um problema público. O ObservAInova não publica sugestões da IA: metadados permanecem públicos, candidatos semânticos ficam privados e somente versões integralmente validadas pela equipe central, aprovadas por outra pessoa e projetadas pelo outbox aparecem na API pública.

## Recorte do corpus inicial

- teses e dissertações de instituições públicas sediadas em Pernambuco;
- todas as áreas do conhecimento;
- janela analítica de 2016 a 2025 e acompanhamento corrente de 2026;
- pilotos de coleta: UFPE e IFPE;
- produções de instituições externas apenas por estudarem Pernambuco ficam fora desta fase.

## Executar localmente

Copie `apps/api/.env.example` e `apps/web/.env.example` para arquivos `.env`, substitua somente os valores locais e execute:

```bash
docker compose -f infra/compose.yaml up --build
docker compose -f infra/compose.yaml exec api alembic upgrade head
```

O ambiente local aceita tokens HS256 apenas com `APP_ENV=development` e `AUTH_MODE=local`. Crie identidades distintas para curadoria e supervisão:

```bash
cd apps/api
uv run python - <<'PY'
from datetime import datetime, timedelta, timezone
import jwt
secret = "substitua-pelo-LOCAL_AUTH_SECRET"
for subject, roles in (("curador-local", ["curator"]), ("supervisor-local", ["supervisor"]), ("admin-local", ["admin"])):
    claims = {"iss":"observainova-local","sub":subject,"aud":"observainova-api","roles":roles,"exp":datetime.now(timezone.utc)+timedelta(hours=8)}
    print(subject, jwt.encode(claims, secret, algorithm="HS256"))
PY
```

O modo local é recusado quando `APP_ENV=production`. Em produção configure OIDC Authorization Code + PKCE na aplicação web e issuer, audiência, JWKS, algoritmo, claim de papéis e mapeamento de papéis na API. Tokens ficam em `sessionStorage`; não devem entrar em URL, HTML ou logs.

## Do repositório à publicação

1. O conector coleta metadados do repositório institucional.
2. A política de elegibilidade mantém apenas tese/dissertação, instituição pública de PE e ano permitido.
3. O documento é obtido somente de host autorizado, com limite de 100 MiB, timeout, redirecionamentos e checksum.
4. O texto integral é a fonte preferida. Resumo é fallback identificado; PDF digitalizado segue para `ocr_required` e fila de OCR/revisão manual.
5. O provedor de extração produz candidatos privados, cada alegação ligada a trecho, página ou posição e nível de confiança interno.
6. A amostra estratificada preserva instituição, área, ano, tipo e escopo. Calibração e teste nunca se misturam.
7. O curador decide os 14 campos, um a um. Aceite e correção exigem fundamento; correção exige justificativa.
8. A versão validada é imutável. Outra identidade supervisora publica, devolve, substitui ou revoga.
9. O outbox cria uma projeção pública idempotente. Revogação desativa imediatamente a projeção.

Filas operacionais: preparação de documento, extração de candidatos e eventos de publicação. Falhas transitórias podem ser reprocessadas; runs, decisões e versões não são sobrescritos. Para OCR, resolva o arquivo fora da fila automática, grave nova versão de texto com método `ocr` ou `manual` e reexecute a extração. Para publicação presa em `processing`, confirme o estado da projeção e reenvie o mesmo evento: o processador é idempotente.

## Provedores e limites

Use `CLAIMS_PROVIDER=deterministic` em desenvolvimento e CI. Para provedor HTTP, configure endpoint, chave, modelo, timeout, versão do esquema e versão de instrução. Nunca armazene chave no repositório. A allow-list do DSpace deve conter somente hosts institucionais aprovados; redirecionamentos para outros hosts são rejeitados.

## Avaliação da tese

Administradores exportam JSON ou CSV em `/api/v1/internal/evaluation/sampling-runs/{id}.json` e `.csv`. O relatório separa calibração e teste e contém precisão, revocação, F1, alegações sem suporte, correções, aceites com fundamento, concordância entre avaliadores, tempo de revisão/publicação, devoluções, proveniência, separação de atores e visibilidade de revogações. Denominadores vazios são `null`, não zero. O CSV neutraliza células iniciadas por `=`, `+`, `-` ou `@`.

## Backup, restauração e verificação

O comando abaixo cria um banco PostgreSQL temporário com nome validado, inclui uma contribuição-marcador com identificadores aleatórios no backup, restaura o dump, verifica a revisão `0019_return_correction_workflow`, as estruturas da fase e o marcador, e remove somente o marcador criado pelo próprio teste e o banco temporário:

```bash
make backup-restore-smoke
```

Verificação completa:

```bash
make check
cd apps/web && npm run test:e2e
cd ../api && uv run python -m pytest tests/api/test_contribution_governance_e2e.py -v
```

Em incidentes, preserve primeiro logs, IDs de run/evento e checksums. Não publique candidatos para “destravar” fila. Restaure o PostgreSQL e o armazenamento de objetos como um par compatível, aplique migrações, valide checksums e só então retome workers.
