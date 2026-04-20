# SIRHOSP

## SIRHOSP - Sistema Interno de Relatórios Hospitalares - Extração Inteligente de Dados Clínicos

Sistema interno para extração automatizada de dados clínicos do sistema fonte hospitalar, armazenamento em banco paralelo e geração de consultas rápidas, buscas textuais e resumos direcionados para gestão, qualidade, jurídico e diretoria.

## Status

Fase inicial de especificação e fundação arquitetural.

## Objetivo da fase 1

Entregar uma primeira versão utilizável que permita:

1. extrair dados do sistema fonte em janelas programadas
2. armazenar os dados em PostgreSQL
3. consultar rapidamente por paciente, período e internação
4. realizar busca livre por palavras-chave no texto clínico
5. gerar resumo de internação atualizado
6. oferecer login interno simples com perfis básicos

## Escopo prioritário da fase 1

- evolução médica
- prescrições
- pacientes internados atualmente
- resumo de internação
- busca textual livre
- dashboard operacional básico

## Decisões arquiteturais iniciais

- **Aplicação principal:** Django
- **Banco de dados:** PostgreSQL
- **Jobs agendados:** systemd timers ou cron
- **Coordenação de execução:** PostgreSQL com locks e tabelas de controle
- **Automação web:** Playwright + Python
- **Gerenciamento de ambiente e dependências Python:** uv
- **Frontend inicial:** Django Templates + HTMX + Bootstrap
- **Busca textual:** PostgreSQL Full Text Search
- **Integração LLM:** camada própria, desacoplada da captura

## Documentação inicial

- [Arquitetura inicial](docs/architecture.md)
- [ADRs](docs/adr/README.md)
- [ADR-0001](docs/adr/ADR-0001-monolito-django-postgresql-e-jobs-agendados.md)

## Princípios iniciais

- não usar dados reais no repositório
- manter credenciais fora do Git
- separar modo laboratório de automações do modo produção
- tratar o projeto como sistema interno institucional, mas sem supercomplexidade desnecessária
- privilegiar simplicidade operacional na fase 1
- padronizar setup e execução local com `uv`
