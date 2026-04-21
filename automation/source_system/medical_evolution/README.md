# Medical Evolution Connector

Conector legado de evoluções médicas internalizado no SIRHOSP.

Arquivos principais:

- `path2.py`: fluxo Playwright para captura de evoluções por intervalo.
- `source_system.py`: helpers de navegação/autenticação/download no sistema legado.
- `processa_evolucoes_txt.py`: normalização/parse de texto extraído do PDF.
- `config.py`: configuração de ambiente do fluxo legado.

Variáveis necessárias para execução real:

- `SOURCE_SYSTEM_URL`
- `SOURCE_SYSTEM_USERNAME`
- `SOURCE_SYSTEM_PASSWORD`
