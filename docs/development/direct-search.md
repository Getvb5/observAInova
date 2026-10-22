# Busca por expressão

A página inicial usa uma expressão de busca para apresentar resultados diretamente.
Não é necessário preencher o questionário de formulação nem confirmar um problema.
Os filtros por instituição, tipo, ano e ordenação aparecem depois da primeira busca.
A consulta e os filtros ficam no endereço para permitir recarregamento e navegação.

## Recuperação e limites

`GET /api/v1/productions/search?q=segurança+do+paciente` recupera as versões atuais
de metadados públicos de teses e dissertações, no período de análise configurado
(2016–2025), de fontes identificadas como instituições públicas sediadas em PE.
O preenchimento desses atributos da fonte é obrigatório para inclusão.

A recuperação é textual, insensível a caixa e aos acentos portugueses. Busca termos
em títulos, resumos, palavras-chave e valores científicos de projeções publicadas
ativas. A ordenação prioriza cobertura dos termos; títulos e palavras-chave têm
peso adicional. Não há promessa de equivalência semântica nem percentual de confiança.
Os resultados podem conter apenas parte dos termos da expressão.

Metadados e contribuições validadas são apresentados com identificação distinta.
Interpretações científicas não publicadas ou revogadas não são pesquisadas nem
retornadas. A busca não cria problemas públicos, aprovações ou registros no acervo.
O fluxo interno de curadoria e supervisão permanece disponível.

## Execução

O navegador usa o proxy do próprio site, preservando a proteção de acesso existente.
Defina `API_INTERNAL_URL` no servidor web: `http://localhost:8000` para execução
local separada, `http://api:8000` no Compose ou o endereço privado do backend na
implantação. Essa variável não deve receber prefixo `NEXT_PUBLIC_`.

Os testes da API cobrem recorte do acervo, normalização, ordenação, filtros,
paginação, validação da consulta e exclusão de interpretações não publicadas.
Os testes da interface cobrem busca com Enter, tentativa após falha, restauração
pelo endereço e refinamento. Os testes de navegador usam fixtures explicitamente
identificadas como dados de teste e credenciais descartáveis somente locais.
