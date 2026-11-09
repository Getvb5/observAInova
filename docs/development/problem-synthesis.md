# Resposta ao problema público

`POST /api/v1/answers` recebe `q` e os filtros opcionais `institution`, `type` e
`publication_year`. A interface solicita a resposta automaticamente após a mesma
expressão usada na busca. A lista aparece enquanto a síntese é processada.

A análise usa até cinco trabalhos com texto disponível dentre os primeiros doze
resultados por relevância textual, no mesmo corpus da busca. Até três trechos de
1.800 caracteres por trabalho são enviados ao provedor. Texto integral já
processado e permitido tem prioridade; na ausência dele, usa-se o resumo da versão
corrente. A resposta identifica o escopo e as páginas disponíveis. Não há download
de PDFs pela requisição de busca nem alegação de leitura integral/exaustiva.

Cada parágrafo é marcado como achado ou inferência e contém IDs de trechos e
citações literais. O servidor verifica se a citação existe no material enviado.
Isso não verifica a correção semântica: a síntese é rotulada como preliminar e sem
revisão humana. Não cria contribuições validadas nem altera curadoria ou supervisão.

## Configuração no servidor

Definir somente no serviço `worker` da Railway:

```dotenv
ANSWER_ENABLED=true
ANSWER_ENDPOINT_URL=https://api.openai.com/v1/chat/completions
ANSWER_MODEL=<modelo compatível com Structured Outputs>
ANSWER_API_KEY=<segredo configurado no painel>
ANSWER_TIMEOUT_SECONDS=45
```

O adaptador usa Chat Completions com `response_format.json_schema`, `strict=true`,
`store=false` e no máximo 6.000 tokens de saída. Contrato verificado na documentação:
https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat

O provedor recebe a expressão, metadados públicos e os trechos selecionados.
Não colocar a chave em variáveis `NEXT_PUBLIC_*`, no repositório ou em mensagens.
Sem ativação, chave e modelo, o endpoint informa indisponibilidade; não há modo
de demonstração que simule resultados científicos. Há limite local de duas
chamadas simultâneas por processo, sem repetição automática de chamadas cobradas.
O app permanece privado; esse limite não é uma política de cotas por usuário para
uso público em larga escala.

## Verificação e limites

Testes cobrem transporte e respostas sintéticas, corpus, privacidade, citações,
texto corrente, retirada de acesso e interação da interface. Não comprovam a
qualidade de um modelo real. Antes de ativar, avaliar problemas reais comparando
cada afirmação às fontes e examinando inferências exageradas.

A auditoria de 30/10/2026 encontrou UFPE com política `metadata_only` e problemas
de ano e vínculo institucional. Nessa configuração, a análise será baseada em
resumos e em um acervo parcial. Este recurso não resolve essas pendências.

A revisão independente identificou uma restrição mais recente sem versão de
texto: a seleção agora consulta primeiro o estado do documento mais recente,
impedindo que um texto antigo seja enviado ao provedor. Também foram corrigidas
mensagens cortadas e respostas malformadas do provedor. Todos têm regressões.

O teste de navegador foi preparado, mas sua execução anterior ficou bloqueada
pela ausência do executável Chromium. Não houve teste de inferência real nem
ativação em produção nesta etapa.
