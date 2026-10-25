# Tasks: add-user-profile-and-self-service-password

## 1. SLICE-AUP-S1 — Página de perfil e troca de senha própria

- [x] 1.1 RED: testes de integração de `/perfil/` (anônimo → login;
      identidade somente leitura; senha atual errada rejeitada; troca
      válida autentica e preserva sessão; validador rejeita senha fraca)
- [x] 1.2 GREEN: view/form/URLs em `apps/accounts` + templates Bootstrap + link "Perfil" no sidebar
- [x] 1.3 Verificação local + gates do slice (check + unit + lint +
      typecheck + `uv run openspec validate
    add-user-profile-and-self-service-password --strict`)

## 2. SLICE-AUP-S2 — Senha provisória e troca obrigatória

- [x] 2.1 RED: testes do middleware (flag → redirect; allowlist; troca
      limpa flag; sem flag não redireciona) e do comando
      `create_portal_user` (cria comum ativo com flag; senha impressa
      autentica; `--reset-password` reemite; duplicado falha)
- [x] 2.2 GREEN: `UserProfile` + migration, middleware registrado,
      limpeza da flag na troca, comando de provisionamento
- [x] 2.3 Verificação local + gates do slice (check + unit +
      integration + lint + typecheck + `uv run openspec validate
    add-user-profile-and-self-service-password --strict`)

## 3. Encerramento (controller)

- [x] 3.1 Review independente por slice (worker fresh + reviewer fresh;
      fix cycle P0/P1 máx. 2 rodadas) — S1: ACCEPT 1ª; S2: ACCEPT 1ª
- [x] 3.2 Gate final do change (quality-gate completo)
- [x] 3.3 Ativação operacional: provisionar as 5 enfermeiras com senha
      provisória; acompanhar primeiro login de cada uma. A conta da
      diretora NÃO é tocada (decisão do operador 2026-09-08: senha forte
      existente permanece, sem reset e sem troca forçada — usuários sem
      perfil não são afetados pelo middleware). Fechada 2026-10-21:
      confirmação do operador de que as enfermeiras foram adicionadas;
      verificação read-only em produção mostra 13 usuários ativos
      não-superuser, com primeiros logins já registrados para parte da
      equipe; enfermeiras ainda sem primeiro login seguem com senha
      provisória até o primeiro acesso, quando o autopreparo de senha
      exige a troca.
