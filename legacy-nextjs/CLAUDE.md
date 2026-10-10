# E-Find

Sistema de gestão de campanha eleitoral (Next.js 15 + Prisma + Tailwind v4). **Leia `docs/ARCHITECTURE.md` antes de alterar código** — ele define a hierarquia, as regras de isolamento entre campanhas, o modelo de permissões, as convenções e os contratos entre módulos.

Regras essenciais:
- Interface em português do Brasil; identificadores de código em inglês; mobile-first.
- Toda leitura/escrita de dados de campanha passa pelos helpers de escopo de `src/server/access.ts` e começa com `authorize(...)`/`requirePermission(...)` de `src/lib/auth.ts`. Nunca confie em `campaignId` ou ids vindos do cliente sem validar escopo.
- Disparos de WhatsApp somente para eleitores com consentimento (`MESSAGEABLE_WHERE`) e somente por provedores oficiais (Meta Cloud API, Twilio, 360dialog) ou o simulador.
- Use o kit `@/components/ui` e o painel de filtros `@/components/filters/voter-filters-panel`.
- Verificação: `npx tsc --noEmit`, `npm test`, `npm run lint`, `npm run build`.
