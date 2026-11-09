# Problem Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Responder ao problema público com leitura rastreável das pesquisas.
**Architecture:** Endpoint de síntese separado, evidência pública corrente,
provedor HTTP configurável e resposta na tela antes da lista de resultados.
**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, httpx, Next.js e React existentes.
**Spec:** docs/superpowers/specs/2026-11-08-problem-synthesis-design.md

## Global Constraints

Uma expressão; corpus/privacidade existentes; sem mudanças na governança;
citações conferidas; resumos/trechos identificados; sem simular IA em produção.

## Review Focus

Respostas atrasadas; fontes antigas/restritas; citações sem validação semântica;
filtros versus paginação; ausência/falha do provedor preservando a busca.

## Task 1: API e evidências

- [x] Testes inicialmente falharam por endpoint ausente; implementar
  `answers/{schemas,evidence,provider,service,router}.py` e registrar rota.
- [x] Testar corpus, privacidade, escopo de leitura, citações, filtros, limites,
  transporte HTTP, indisponibilidade e insuficiência de evidência.
- [x] Revisão independente; reproduzir e corrigir uso de texto antigo após
  restrição nova sem versão de texto; corrigir mensagens e payloads nulos.

## Task 2: Interface e integração

- [x] Testes inicialmente falharam por componente ausente; implementar
  `ResearchAnswer` e `answer-api.ts`, ligar à busca sem novas perguntas.
- [x] Testar leitura identificada, referências, estados, troca de contexto e
  ausência de nova chamada ao paginar/ordenar.
- [x] Documentar ativação, limites do corpus e necessidade de avaliação real.
- [ ] Salvar branch remotamente após verificação final.
- [ ] Conectar provedor, avaliar respostas reais e ativar em produção.

As alterações locais foram recuperadas após manutenção do ambiente; não houve
mudança no site publicado durante a recuperação. Teste visual de navegador
permanece pendente por falta do Chromium.
