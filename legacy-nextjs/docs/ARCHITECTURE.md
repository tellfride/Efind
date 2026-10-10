# E-Find — Arquitetura e contratos

Sistema de gestão de campanha eleitoral (efind.com.br): cadastro de eleitores por link/QR Code vinculado
a quem cadastrou, equipe hierárquica com permissões, mapa por bairro a partir do CEP, dashboards
personalizáveis e disparo de WhatsApp **somente para quem consentiu**.

Interface 100% em **português do Brasil**. Usuários de campo (cabos eleitorais) usam o **celular**:
toda tela precisa funcionar bem em 360px de largura.

## Stack

| Camada | Escolha |
| --- | --- |
| Framework | Next.js 15.5 (App Router, Server Components, Server Actions), React 19, TypeScript estrito |
| Banco | Prisma 6 — SQLite em dev (`prisma/dev.db`), PostgreSQL em produção (trocar `provider`) |
| Estilo | Tailwind CSS v4 (tokens em `src/app/globals.css`: cor `brand-*`, `whatsapp`) + kit em `src/components/ui` |
| Ícones | lucide-react |
| Gráficos | recharts 3 |
| Mapa | leaflet 1.9 + react-leaflet 5 + leaflet.markercluster + leaflet.heat (sempre `dynamic(..., { ssr: false })`) |
| Validação | zod 3 |
| Sessão | JWT HS256 (jose) em cookie httpOnly `efind_session`; bcryptjs para senhas |
| Arrastar/soltar | @dnd-kit |
| QR Code | qrcode (helper em `src/lib/qrcode.ts`) |
| Toasts | sonner (`import { toast } from "sonner"`; `<Toaster>` já está no layout raiz) |
| Testes | vitest (`tests/**/*.test.ts`, alias `@/` configurado) |

## Hierarquia e isolamento

```
SUPER_ADMIN (plataforma — /super)        cria campanhas (candidatos); NÃO vê dados pessoais de eleitores
└── Campaign (tenant)                    nenhum candidato enxerga a campanha do outro
    ├── ADMIN          (acesso total à campanha; define permissões)
    │   └── COORDENADOR (parentId = admin)       vê a própria rede: ele + cabos com parentId = ele
    │       └── CABO    (parentId = coordenador) vê só os eleitores que ele cadastrou
    └── Voter.registeredById → quem cadastrou (sempre preenchido)
```

**Regras invioláveis (segurança):**

1. Toda consulta de dados de campanha filtra por `campaignId` do usuário logado — nunca por um id vindo do cliente.
2. Eleitores: use **sempre** `buildVoterWhere(user, filters)` / `voterScopeWhere(user)` / `findVoterInScope(user, id)`
   de `src/server/access.ts`. Filtros nunca ampliam o escopo (são combinados com AND).
3. Equipe: use `teamScopeWhere(user)` / `canAccessTeamMember(user, id)`.
4. Toda Server Action e Route Handler começa com `authorize(module, action)` (ou `authorizeSuperAdmin()`),
   e toda página com `requirePermission(module, action)` / `requireAdmin()` / `requireSuperAdmin()` — de `src/lib/auth.ts`.
   O middleware só verifica se há sessão; **a autorização real é sua responsabilidade em cada rota/ação**.
5. Ids recebidos do cliente (ex.: `registeredById`, `parentId`, `templateId`, `connectionId`) devem ser
   validados como pertencentes à campanha **e** ao escopo do usuário antes de usar.
6. Credenciais de WhatsApp: gravadas com `encryptJson` (`src/lib/crypto.ts`), nunca devolvidas ao navegador
   em claro (use `maskSecret`).
7. Registre na auditoria (`audit()` de `src/lib/audit.ts`) criações, alterações, exclusões, exportações,
   mudanças de permissão e disparos.
8. Não logue dados pessoais (telefone, e-mail) em `console.*`.

## Permissões (`src/lib/permissions.ts`)

Módulos: `dashboard`, `eleitores`, `mapa`, `meu_link`, `equipe`, `modelos`, `disparos`, `whatsapp`,
`configuracoes`, `auditoria`. Ações: `view`, `create`, `edit`, `delete`, `export` (cada módulo suporta um subconjunto).

- ADMIN: sempre tudo. A matriz de permissões (`/painel/permissoes`) é exclusiva do ADMIN (não delegável).
- COORDENADOR/CABO: padrão do papel (`DEFAULT_ROLE_PERMISSIONS`) → linhas `RolePermission` da campanha →
  exceções `UserPermission` (null = herda). Sem `view` nenhuma outra ação vale.
- `getSessionUser()` já devolve `user.permissions` resolvido; use `can(user.permissions, module, action)`.
- Mesmo com permissão de `equipe.create`, um COORDENADOR só cria **CABO** abaixo de si; nunca altera papéis.

## Convenções de código

- **Leituras**: em Server Components, direto com Prisma + helpers de escopo.
- **Mutações**: Server Actions em `actions.ts` ao lado da página (`"use server"`), retornando
  `ActionResult` (`src/lib/action-result.ts`) e usadas com `useActionState` no cliente.
  Validação com zod no servidor (`zodToActionError`). Depois de mutar: `revalidatePath(...)`.
- **Dados para componentes cliente** (mapa, widgets, contagens ao vivo): Route Handlers em `src/app/api/painel/<módulo>/...`
  (o middleware devolve 401 sem sessão; ainda assim chame `authorize`).
- `params` e `searchParams` de páginas são **Promises** (Next 15): `const { id } = await params`.
- Filtros de eleitores na URL: `parseVoterFilters(searchParams)` / `voterFiltersToSearchParams(filters)` (`src/lib/voter-filters.ts`).
- Paginação: `<Pagination>` + `parsePage()` de `src/components/ui/pagination.tsx` (25 por página).
- Datas exibidas com `formatDate`/`formatDateTime` (fuso America/Sao_Paulo); números com `formatNumber`.
- Telefones: armazenar `normalizeBrPhone()` (`55DDNNNNNNNNN`), exibir `formatPhone()`, inputs com `maskPhoneInput()`.
- CEP: `normalizeCep`/`formatCep`/`lookupCep` (`src/server/geo/cep.ts`); no cliente, `GET /api/public/cep/{cep}`.
- Geocodificação: `geocodeVoter(id)` (`src/server/geo/geocode.ts`) — chame após criar/alterar endereço com
  `after(() => geocodeVoter(id))` de `next/server`, ou deixe `geoStatus = "PENDING"` para o worker.
- Valores "enum" (papéis, status, cargos...) e rótulos em pt-BR: `src/lib/constants.ts`.
- Campos `Json` do Prisma (SQLite suporta): `Dashboard.widgets`, `Broadcast.filters`, `Campaign.formConfig`,
  `MessageTemplate.providerVariables`, `AuditLog.details`.
- Busca `contains` no SQLite já é case-insensitive (ASCII). Não use `mode: "insensitive"` (não existe no cliente SQLite).
- Código de servidor usado pelo **worker** (`scripts/worker.ts`) não pode importar `next/*` nem `@/lib/auth`
  (processador de disparos, geocodificação, provedores de WhatsApp).
- Componentes cliente não podem importar `@/lib/db`, `@/lib/auth`, `@/server/**` (exceto Server Actions marcadas com `"use server"`).

## Kit de UI (`@/components/ui`)

`Button`, `ButtonLink`, `buttonClasses` · `Input`, `Textarea`, `Select`, `Checkbox`, `Label`, `Field`, `FieldError`, `FormMessage` ·
`Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter` · `Badge` (tones: gray, brand, green, yellow, red, blue, purple) ·
`Table`, `THead`, `TBody`, `TR`, `TH`, `TD`, `TableEmpty` · `PageHeader`, `EmptyState`, `StatCard`, `Spinner`, `Skeleton`, `Avatar`,
`ProgressBar`, `Alert` · `Pagination`, `parsePage` · cliente: `SubmitButton`, `ConfirmSubmitButton`, `CopyButton`, `Switch`, `Modal`, `Tabs`.

Layout do painel (sidebar + topo) já existe em `src/app/painel/layout.tsx` e `src/app/super/layout.tsx`; páginas
renderizam só o conteúdo, começando por `<PageHeader title=... description=... actions=... />`.
Estilo: cartões brancos `rounded-xl border-slate-200`, cor de ação `brand-600`, fundo `slate-50`.

## Rotas

| Rota | Módulo |
| --- | --- |
| `/login` | login (pronto) |
| `/c/[code]` (+ `/obrigado`, `/privacidade`) | formulário público de cadastro (link/QR de cada usuário) |
| `/painel` | dashboard padrão |
| `/painel/dashboards`, `/painel/dashboards/[id]`, `/painel/dashboards/[id]/editar` | dashboards personalizáveis |
| `/painel/eleitores`, `/novo`, `/[id]`, `/importar` | eleitores |
| `/painel/mapa` | mapa por bairro |
| `/painel/meu-link` (+ `/cartaz`) | link e QR Code pessoal |
| `/painel/equipe`, `/novo`, `/[id]` | equipe |
| `/painel/permissoes` | matriz de permissões (ADMIN) |
| `/painel/mensagens/modelos`, `/painel/mensagens/disparos`, `/novo`, `/[id]` | modelos e disparos |
| `/painel/whatsapp` | conexões de API do WhatsApp |
| `/painel/configuracoes`, `/painel/auditoria`, `/painel/perfil` | campanha, auditoria e conta |
| `/super`, `/super/campanhas`, `/nova`, `/[id]`, `/super/usuarios`, `/super/auditoria`, `/super/perfil` | super admin |
| `/api/public/cep/[cep]` | consulta de CEP (pronto) |
| `/api/webhooks/whatsapp/[token]` | webhook dos provedores |
| `/api/cron/tick` | processamento de fila (agendador externo) |

## Contratos entre módulos

- `src/server/whatsapp/types.ts` — interface `WhatsAppProvider`, `ProviderDefinition`, `OutgoingMessage`, `WebhookEvent`.
- `src/server/whatsapp/registry.ts` — `PROVIDERS`, `getProviderDefinition(key)`, `providerForConnection(conn)`, `getDefaultConnection(campaignId)`.
- `src/server/messaging/counters.ts` — `refreshBroadcastCounters(broadcastId)` (chamado pelo webhook após atualizar status).
- `src/server/dashboard/presets.ts` — `createDefaultDashboards(tx, campaignId)` (chamado por `bootstrapCampaign`).
- `src/server/campaign/bootstrap.ts` — `bootstrapCampaign(tx, campaignId)`: permissões padrão + dashboards (pronto).
- `src/lib/template-vars.ts` — `TEMPLATE_VARIABLES`, `renderTemplate`, `buildTemplateContext` (pronto).
- `src/lib/qrcode.ts` — `registrationUrl(inviteCode, "link"|"qr")`, `qrDataUrl`, `qrSvg` (pronto).
- `src/components/account/account-forms.tsx` — `ChangePasswordForm`, `ProfileForm` (pronto).
- `src/components/filters/voter-filters-panel.tsx` — `VoterFiltersPanel` (controlado), `UrlVoterFilters` (sincroniza com a URL),
  `VoterFiltersSummary`; opções via `getVoterFilterOptions(user)` de `src/server/filter-options.ts` (prontos). Use-os em
  toda tela que filtra eleitores (lista, mapa, widgets, público de disparo) para manter a mesma experiência.
- `MultiSelect` (`src/components/ui/multi-select.tsx`) — seleção múltipla com busca (pronto).
- `MESSAGEABLE_WHERE` (`src/server/access.ts`) — eleitor apto a disparo: `whatsappOptIn = true`, `optOutAt = null`, `consentAt != null`.

## Conformidade (LGPD e TSE)

- Formulário público exige **consentimento LGPD** explícito (checkbox não pré-marcado) e oferece opt-in
  **separado** para WhatsApp. Guardar `consentAt`, `consentIp`, `consentText`.
- Disparos só para `MESSAGEABLE_WHERE`. Resposta "SAIR" (e sinônimos em `OPT_OUT_KEYWORDS`) descadastra.
- Res. TSE nº 23.610/2019 (art. 28, IV, e art. 34): é vedado disparo em massa sem consentimento e por
  ferramentas não fornecidas pelo provedor do aplicativo ou contrárias aos seus termos de uso. Por isso
  o E-Find integra **apenas** a API oficial do WhatsApp (Meta Cloud API) e parceiros oficiais (Twilio,
  360dialog), além de um **Simulador** para testes. Não integrar APIs não oficiais (Z-API, Evolution etc.).
- Exportações e exclusões de eleitores são auditadas. Exclusão de eleitor é definitiva (direito do titular).

## Desenvolvimento

```bash
npm install
npx prisma migrate dev     # cria prisma/dev.db
npm run db:seed            # super admin + campanha demo
npm run dev                # http://localhost:3000
npm run worker             # fila de disparos + geocodificação (outro terminal)
npm test                   # vitest
```

Contas do seed (somente dev): `super@efind.com.br` (senha em `SEED_SUPERADMIN_PASSWORD` no `.env`);
`admin@demo.efind.com.br`, `coord1@demo.efind.com.br`, `cabo1@demo.efind.com.br` — senha `Demo@2026`.
