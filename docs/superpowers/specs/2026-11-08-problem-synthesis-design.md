# Síntese científica ao problema público

Requisito de Getúlio: uma única expressão deve recuperar teses/dissertações e
produzir resposta contextualizada sobre possibilidade, caminhos, potenciais e
limites de enfrentamento do problema público.

Usar a busca existente e o texto disponível. Respostas preenchidas por templates
não atendem ao requisito. Buscar PDFs a cada consulta duplicaria o pipeline;
preferir versões processadas e permitidas, com fallback explícito ao resumo.

Contrato: resposta automática preliminar, separada das contribuições validadas;
mesmo corpus e filtros; até cinco trabalhos entre os primeiros doze resultados;
três trechos de até 1.800 caracteres por fonte. Sem dados privados ou textos
revogados. Cada afirmação tem trecho identificável e citação literal conferida,
distinguindo achado e inferência. Citação localizada não equivale a validação
semântica ou humana. Não prometer viabilidade fora do contexto estudado.

Insuficiência deve ser explícita, sem se confundir com impossibilidade. Sem IA
configurada ou com falha/citação inválida, informar indisponibilidade. Resultados
bibliográficos continuam acessíveis. Nova expressão/filtro limpa respostas
anteriores; paginação e ordenação não geram nova chamada ao modelo.

O provedor recebe somente a expressão, metadados públicos e trechos selecionados.
É configurado no servidor e fica desabilitado até a conexão estar pronta. Não
alterar a visibilidade privada nem políticas de direitos existentes.

Limites: falta conexão de IA no servidor; UFPE metadata_only implica resumos;
problemas de normalização do acervo são pendências distintas. Testes com fixtures
verificam fluxo/contratos, não a qualidade de respostas reais.
