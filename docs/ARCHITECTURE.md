# E-Find — Arquitetura e contratos (Django + MariaDB)

Sistema de gestão de campanha eleitoral (efind.com.br): cadastro de eleitores por link/QR Code vinculado a quem
cadastrou, equipe hierárquica com permissões, mapa por bairro a partir do CEP, dashboards personalizáveis e disparo
de WhatsApp **somente para quem consentiu**.

Interface 100% em **português do Brasil**. Cabos eleitorais usam o **celular**: toda tela precisa funcionar bem em
360 px de largura. Identificadores de código em inglês; textos para o usuário em pt-BR com acentuação correta.

> O projeto começou em Next.js; esse código está arquivado em `legacy-nextjs/` **apenas como referência** de
> regras, textos e lógica (portar, não copiar às cegas). Nada em `legacy-nextjs/` é executado.

## Stack

| Camada | Escolha |
| --- | --- |
| Backend | Django 5.2 LTS, Python 3.11+ (dev: 3.13 em `.venv/`), views em função + decorators, formulários Django |
| Banco | **MariaDB** (utf8mb4) via `mysqlclient`; sem `DB_NAME` no `.env` cai em SQLite local só para desenvolvimento. Testes usam SQLite em memória |
| Front | Templates Django + **Tailwind CSS v4** (compilado) + **HTMX** + **Alpine.js**; Chart.js (gráficos), Leaflet (+markercluster, +heat) (mapa), SortableJS (arrastar). Tudo local em `static/vendor/` (sem CDN) |
| Ícones | Lucide em `static/icons/*.svg`, usados com `{% icon "nome" "classes" %}` |
| Sessão/Auth | Sessões do Django (cookie `efind_session`, banco), login por e-mail (`apps.accounts.backends.EmailBackend`), PBKDF2 |
| Criptografia | AES-256-GCM (`cryptography`) para credenciais de WhatsApp (`apps.core.crypto`) |
| QR Code | `segno` (`apps.core.qr`) |
| HTTP externo | `httpx` (CEP, geocodificação, provedores de WhatsApp) |
| Estáticos prod | WhiteNoise. **Produção não precisa de Node** (CSS compilado fica versionado em `static/css/app.css`) |

## Estrutura

```
efind/                 settings.py, urls.py (inclui os urls.py dos apps), wsgi/asgi
apps/
  core/                SEM models de negócio: constants, permissions, access (escopo), voter_filters, filter_options,
                       phone, crypto, utils, qr, ratelimit, template_vars, decorators, middleware, forms, http,
                       nav, context_processors, templatetags/ui.py (kit de UI), stubs
  accounts/            User (+ RolePermission, UserPermission), login/logout, perfil, services.permissions_for
  campaigns/           Campaign, bootstrap_campaign, comando seed_demo
  voters/              Voter  → módulo "voters"  (cadastro público, lista, detalhe, importação, meu link)
  geo/                 CepCache, lookup_cep, geocode_*  (+ API pública de CEP)
  dashboards/          Dashboard, presets  → módulo "dashboards"
  whatsapp/            WhatsAppConnection, InboundMessage, types (contrato), registry → módulo "whatsapp"
  messaging/           MessageTemplate, Broadcast, BroadcastMessage → módulo "messaging" (+ worker)
  auditlog/            AuditLog, service.audit(), actions
  superadmin/          views do super admin (/super/...)
  team/                equipe + matriz de permissões (/painel/equipe, /painel/permissoes)
  mapview/             mapa (/painel/mapa)
  portal/              landing, termos, privacidade, configurações da campanha, auditoria da campanha
templates/             base.html, layouts/, components/, errors/, accounts/ e uma pasta por módulo (templates/<app>/)
static/                css/app.css (GERADO), js/app.js, js/<módulo>/..., vendor/, icons/, img/
assets/css/app.css     fonte do Tailwind (componentes semânticos .btn .input .card .badge ...)
docs/                  este arquivo, MARIADB.md, DEPLOY.md
legacy-nextjs/         referência arquivada (não executa)
```

## Hierarquia e isolamento (regras invioláveis de segurança)

```
SUPER_ADMIN (plataforma — /super)        cria campanhas (candidatos); NÃO vê dados pessoais de eleitores
└── Campaign (tenant)                    nenhum candidato enxerga a campanha do outro
    ├── ADMIN          (acesso total à campanha; define permissões)
    │   └── COORDENADOR (parent = admin)        vê a própria rede: ele + cabos com parent = ele
    │       └── CABO    (parent = coordenador)  vê só os eleitores que ele cadastrou
    └── Voter.registered_by → quem cadastrou (sempre preenchido)
```

1. Toda consulta de dados de campanha filtra por `campaign_id` do usuário logado — **nunca** por id vindo do cliente.
2. Eleitores: use **sempre** `voter_scope(user)`, `voters_queryset(user, filters)` ou `get_voter_in_scope(user, id)` de
   `apps.core.access`. Filtros nunca ampliam o escopo (são AND com o escopo).
3. Equipe: `team_scope(user)`, `get_member_in_scope(user, id)`, `can_access_member(user, id)`.
4. Toda view começa com um decorator de `apps.core.decorators` (ver abaixo). O middleware só carrega contexto
   (`request.campaign`, `request.perms`); **a autorização é responsabilidade de cada view**.
5. Ids recebidos do cliente (`registered_by`, `parent`, `template`, `connection`, `voter`...) devem ser validados como
   pertencentes à campanha **e** ao escopo do usuário antes de usar (nunca `Model.objects.get(pk=...)` solto).
   `pk` malformado (UUID inválido) levanta `ValidationError`: use os helpers de escopo, que já tratam isso.
6. Credenciais de WhatsApp: gravadas com `encrypt_json`, nunca devolvidas em claro ao navegador (`mask_secret`).
7. Audite criações, alterações, exclusões, exportações, mudanças de permissão e disparos: `audit("voter.export", request=request, entity="Voter", details={"count": n})`
   (`apps.auditlog.service`). `details` **sem dados pessoais** (use ids e contagens).
8. Não logue dados pessoais (telefone, e-mail, nome) em `logger`/`print`.
9. SQL: só ORM com parâmetros (nunca interpolar entrada em `raw()`/`extra()`); HTML: autoescape ligado, `|safe`/`mark_safe`
   só em conteúdo gerado por você (nunca em dados do usuário); `json_script` para passar dados ao JS.
10. POST/PUT/DELETE sempre com CSRF (`{% csrf_token %}`; HTMX já envia `X-CSRFToken` via `hx-headers` do `<body>`);
    ações que mudam estado nunca em GET.

## Permissões (`apps/core/permissions.py`)

Módulos: `dashboard`, `eleitores`, `mapa`, `meu_link`, `equipe`, `modelos`, `disparos`, `whatsapp`, `configuracoes`,
`auditoria`. Ações: `view`, `create`, `edit`, `delete`, `export` (cada módulo suporta um subconjunto — `MODULES[m]["actions"]`).

- ADMIN: sempre tudo. A matriz de permissões (`/painel/permissoes/`) é exclusiva do ADMIN (não delegável).
- COORDENADOR/CABO: padrão do papel (`DEFAULT_ROLE_PERMISSIONS`) → linhas `RolePermission` da campanha → exceções
  `UserPermission` (`None` = herda). Sem `view` nenhuma outra ação vale. Efeito **imediato** (calculado por requisição).
- Nas views: `request.perms` (dict `{módulo: {ação: bool}}`); nos templates: `perms.eleitores.create`.
- Mesmo com `equipe.create`, um COORDENADOR só cria **CABO** abaixo de si; nunca altera papéis.

### Decorators (`apps.core.decorators`)

```python
@module_permission_required("eleitores", "view")         # ADMIN sempre passa; sem permissão → 403
@module_permission_required("eleitores", "export", json_response=True)   # endpoints JSON: 401/403 em JSON
@campaign_user_required                                    # qualquer usuário de campanha logado
@admin_required                                            # somente ADMIN da campanha
@super_admin_required                                      # somente SUPER_ADMIN
```
Sem sessão → redireciona para `/login/?next=`; (HTMX → 401 JSON). 403 renderiza `errors/403.html` no layout do painel.
Para CBVs: `ModulePermissionMixin` (`permission_module`, `permission_action`).

## Convenções de código

- **Views em função** + decorators. GET renderiza; POST processa e faz **redirect** (PRG) com `messages.success/error`
  (viram toasts). Erros de formulário: re-renderize a página com o form ligado.
- **Formulários**: `class MeuForm(StyledFormMixin, forms.Form|ModelForm)` (`apps.core.forms`) aplica as classes do kit
  (`input`, `select`, `textarea`, `checkbox`) e `aria-invalid`. `PhoneField` normaliza telefones para `55DDNNNNNNNNN`.
  Renderize com `{% field form.campo %}` (rótulo + controle + erro/dica).
- **Transações**: operações com várias escritas em `with transaction.atomic():`.
- **Consultas**: sem N+1 (`select_related`/`prefetch_related`/`annotate`/`values().annotate()`); paginação com
  `django.core.paginator.Paginator` (25 por página) + `{% pagination page_obj %}`.
- **Endpoints para JS** (mapa, widgets, contagens ao vivo): views que devolvem `JsonResponse` em `api/painel/<módulo>/...`,
  com `json_response=True` no decorator.
- **Filtros de eleitores** (lista, mapa, widgets, público de disparo): `parse_voter_filters(request.GET)` →
  `voters_queryset(request.user, filters)`; componente `{% voter_filters filters filter_options %}` com
  `get_voter_filter_options(request.user)`. No JS: `EFind.paramsToFilters(new URLSearchParams(new FormData(form)))` e
  `EFind.filtersToParams(filters)` convertem entre querystring e o dict JSON de filtros (`Broadcast.filters`, widgets).
- **Datas**: `USE_TZ=True`, fuso America/Sao_Paulo; no template use `|brdate`, `|brdatetime` ou `|date:"d/m/Y H:i"`.
  Para "hoje/últimos N dias" use `timezone.localtime()`/`localdate()`; dias do gráfico no fuso de São Paulo.
- **Telefones**: guardar `normalize_br_phone()` (`55DDNNNNNNNNN`), exibir `|phone`, inputs com `data-mask="phone"`.
- **CEP**: `normalize_cep`/`lookup_cep` (`apps.geo.cep`); no navegador `data-cep-lookup` (ver JS).
- **Geocodificação**: após criar/alterar endereço, deixe `geo_status=PENDING` e chame
  `apps.geo.geocode.geocode_voter_in_background(voter.pk)` (o worker também processa pendentes).
- **Enums/rótulos**: `apps/core/constants.py` (`TextChoices`; `label_of(Role, valor)`).
- **JSON em campos** (`JSONField`): `Dashboard.widgets`, `Broadcast.filters`, `Campaign.form_config`,
  `MessageTemplate.provider_variables`, `AuditLog.details`.
- Código usado pelo **worker** (`manage.py run_worker`: `apps.messaging.processor`, `apps.whatsapp.registry/providers`,
  `apps.geo.*`) **não pode** depender de `request`, `messages` nem de decorators.
- Em testes e comandos use `Client`/`RequestFactory`; os testes usam SQLite em memória e não acessam a rede
  (mock `httpx`/funções de rede).

## Kit de UI

Templates das páginas estendem `layouts/shell.html` (painel/super: menu + topo) ou `layouts/public.html` (páginas
públicas) e preenchem `{% block title %}Eleitores · E-Find{% endblock %}` e `{% block content %}`. O kit é *builtin*
(não precisa de `{% load %}`):

```django
{% page_header title="Eleitores" description="..." %}<a class="btn btn-primary" href="...">{% icon "plus" %} Novo</a>{% endpage_header %}
{% card title="Resumo" description="..." padding=False css="mb-6" %}...{% endcard %}
{% empty_state icon="inbox" title="Nada aqui" description="..." %}<a class="btn btn-primary">Criar</a>{% endempty_state %}
{% alert "warning" title="Atenção" %}texto{% endalert %}            {# info | success | warning | danger #}
{% stat_card "Eleitores" total icon="users-round" tone="brand" hint="na sua rede" href="/painel/eleitores/" %}
{% badge "Ativo" "green" %}  {% progress 40 100 "green" %}  {% avatar user.name %}  {% icon "users" "size-5 text-brand-600" %}
{% field form.nome hint="..." %}   {% pagination page_obj %}   {% qs page=2 %}   {% voter_filters filters options %}
filtros: |phone |cep |num |pct |brdate |brdatetime |initials |get_item |tags_list |role_label |percent_of
```

Classes semânticas (definidas em `assets/css/app.css`): botões `btn btn-primary|secondary|outline|ghost|danger|success|whatsapp`
+ `btn-sm|btn-lg|btn-icon`; campos `input select textarea checkbox label field-hint field-error`; `card card-header card-title
card-description card-body card-footer`; `badge badge-gray|brand|green|yellow|red|blue|purple`; tabela `table-wrap` + `table`;
`progress progress-bar progress-brand|green|yellow|red`; `avatar`; `alert alert-info|success|warning|danger`; `tabs tab`;
`chip`; `skeleton`; `link`. O resto é utilitário Tailwind (classes completas no HTML — nunca montadas por concatenação).
Estilo: cartões brancos `rounded-xl border-slate-200`, ação principal `brand-600`, fundo `slate-50`.

Ícones: lista em `scripts/icons.txt` (137). Para outro ícone Lucide: `node scripts/vendor.mjs --icon nome1 nome2`
(só copia arquivos para `static/icons/`; não edita arquivos compartilhados).

**CSS**: o Tailwind escaneia `templates/`, `apps/` e `static/js/`. Depois de usar classes novas, rode `npm run build:css`
(idempotente; **nunca edite `static/css/app.css` à mão**). CSS específico de módulo só se imprescindível, em arquivo
próprio `static/css/<módulo>.css`.

**JS** (`static/js/app.js` + Alpine + HTMX, global): toasts (`EFind.toast(msg, level)`, mensagens do Django e
`HX-Trigger: {"toast": ...}` via `apps.core.http.with_toast`), `data-confirm="Tem certeza?"` em botões/forms,
`data-copy="texto"` em botões (copia), máscaras `data-mask="phone|cep"`, preenchimento por CEP
(`<input data-mask="cep" data-cep-lookup data-cep-target="street:#id_street,neighborhood:#id_neighborhood,city:#id_city,state:#id_state">`),
componentes Alpine `toasts`, `dropdown`, `multiSelect`. JS próprio do módulo em `static/js/<módulo>/*.js` (carregue no
`{% block scripts %}` com `{% load static %}`); dados do servidor para o JS via `{{ dados|json_script:"id" }}`.
Alpine e HTMX são carregados em todas as páginas (`defer`, depois de `app.js`).

## Rotas e donos

| Rota | Módulo (app) |
| --- | --- |
| `/login/`, `/logout/` (POST), `/painel/perfil/`, `/super/perfil/` | accounts (pronto) |
| `/api/public/cep/<cep>/` | geo (pronto) |
| `/`, `/privacidade/`, `/termos/`, `/painel/configuracoes/`, `/painel/auditoria/` | portal |
| `/c/<code>/` (+ `obrigado/`, `privacidade/`), `/painel/eleitores/` (+ `novo/`, `<id>/`, `importar/` (+ `modelo/`: planilha-modelo CSV para download), `exportar/`), `/painel/meu-link/` (+ `cartaz/`) | voters |
| `/painel/` e `/painel/dashboards/` (+ `<id>/`, `<id>/editar/`), `/api/painel/dashboard/...` | dashboards |
| `/painel/equipe/` (+ `novo/`, `<id>/`), `/painel/permissoes/` | team |
| `/painel/mapa/`, `/api/painel/mapa/...` | mapview |
| `/painel/mensagens/modelos/`, `/painel/mensagens/disparos/` (+ `novo/`, `<id>/`), `/api/painel/disparos/...`, `/api/cron/tick/` | messaging |
| `/painel/whatsapp/`, `/api/webhooks/whatsapp/<token>/` | whatsapp |
| `/super/`, `/super/campanhas/` (+ `nova/`, `<id>/`), `/super/usuarios/`, `/super/auditoria/` | superadmin |

Cada app declara `app_name` e seus caminhos **completos** em `urls.py` (todos incluídos na raiz em `efind/urls.py`).
`urls.py` hoje contém stubs (`apps.core.stubs`) que cada módulo substitui. O menu lateral usa caminhos literais
(`apps/core/nav.py`) — mantenha esses caminhos de listagem.

## Contratos entre módulos

- `apps/whatsapp/types.py` — `WhatsAppProvider`, `ProviderDefinition`, `OutgoingMessage`, `SendResult`, `WebhookEvent`...
- `apps/whatsapp/registry.py` — `PROVIDERS`, `get_provider_definition(key)`, `provider_for_connection(connection)`,
  `get_default_connection(campaign_id)` (módulo whatsapp implementa; messaging consome).
- `apps/messaging/counters.py` — `refresh_broadcast_counters(broadcast_id)` (messaging implementa; o webhook chama).
- `apps/dashboards/presets.py` — `create_default_dashboards(campaign)` (pronto; dashboards pode estender).
- `apps/campaigns/bootstrap.py` — `bootstrap_campaign(campaign)`: permissões padrão + dashboards (pronto).
- `apps/core/template_vars.py` — `TEMPLATE_VARIABLES`, `render_template`, `build_template_context` (pronto).
- `apps/core/qr.py` — `registration_url(code, "link"|"qr")`, `qr_png_data_url`, `qr_svg` (pronto).
- `apps/core/access.py` — `MESSAGEABLE_Q`: eleitor apto a disparo = `whatsapp_opt_in` + sem `opt_out_at` + `consent_at` (pronto).
- `apps/geo/geocode.py` — `geocode_voter`, `geocode_voter_in_background`, `process_pending_geocoding` (pronto).

## Conformidade (LGPD e TSE)

- Formulário público exige **consentimento LGPD** explícito (checkbox não pré-marcado) e oferece opt-in **separado** para
  WhatsApp. Guardar `consent_at`, `consent_ip`, `consent_text`.
- Disparos só para `MESSAGEABLE_Q`. Resposta "SAIR" (e sinônimos em `OPT_OUT_KEYWORDS`) descadastra.
- Res. TSE nº 23.610/2019 (art. 28, IV, e art. 34): é vedado disparo em massa sem consentimento e por ferramentas não
  fornecidas pelo provedor do aplicativo ou contrárias aos seus termos de uso. Por isso o E-Find integra **apenas** a API
  oficial do WhatsApp (Meta Cloud API) e parceiros oficiais (Twilio, 360dialog), além de um **Simulador** para testes.
  Não integrar APIs não oficiais (Z-API, Evolution, Baileys etc.).
- Exportações e exclusões de eleitores são auditadas. Exclusão de eleitor é definitiva (direito do titular).

## Desenvolvimento (Windows, Git Bash/PowerShell)

```bash
./.venv/Scripts/python.exe manage.py migrate        # cria/atualiza o banco
./.venv/Scripts/python.exe manage.py seed_demo      # super admin + campanha demo (240 eleitores fictícios)
./.venv/Scripts/python.exe manage.py runserver 8000 # http://localhost:8000
                                                    # (com --noreload, reinicie após editar Python OU templates: o cache de templates não recarrega)
./.venv/Scripts/python.exe manage.py run_worker     # fila de disparos + geocodificação (outro terminal)
PYTHONUTF8=1 ./.venv/Scripts/python.exe manage.py test apps          # todos os testes
PYTHONUTF8=1 ./.venv/Scripts/python.exe manage.py test apps.voters   # um módulo
./.venv/Scripts/python.exe manage.py check
npm run build:css                                   # recompila o Tailwind
```

Contas do seed (somente dev): `super@efind.com.br` (senha em `SEED_SUPERADMIN_PASSWORD` no `.env`);
`admin@demo.efind.com.br`, `coord1@demo.efind.com.br`, `cabo1@demo.efind.com.br` — senha `Demo@2026`.

**Models e migrations são da fundação.** Módulos não alteram `models.py` nem criam migrations; se faltar um campo,
registrem em "mudanças compartilhadas necessárias" e contornem dentro do próprio módulo.

## Contas, senhas e confirmações

- **Senha provisória** (equipe/super admin criam ou redefinem): `User.must_change_password=True`. Enquanto estiver ligado, o
  middleware (`apps/core/middleware.py`) só deixa o usuário abrir o perfil (troca de senha), sair e carregar estáticos;
  `/api/*` e HTMX recebem 403 em JSON. Trocar a senha (perfil ou link do e-mail) desliga a flag. Qualquer novo fluxo que
  gere senha para outra pessoa deve ligar a flag.
- **Recuperação por e-mail** (`apps/accounts/password_reset.py`, rotas `/senha/...`): só existe com e-mail configurado
  (`EMAIL_HOST` no `.env`; em DEBUG imprime no console). Resposta idêntica exista ou não a conta, limite 3/e-mail e 10/IP por
  hora, link de uso único com validade de 1 h montado com `APP_URL` (nunca o cabeçalho Host), senha com letras e números.
  `settings.PASSWORD_RESET_ENABLED` desliga tudo (404 + link some do login) quando não há e-mail.
- **Confirmação de ações**: use `data-confirm="Mensagem?"` no botão/`<form>`; o diálogo é próprio (`EFind.confirm`), porque
  `window.confirm()` é suprimido em WebViews (ex.: navegador do WhatsApp). Título opcional: `data-confirm-title`; o botão
  de confirmar herda o texto e o tom (`btn-danger` → vermelho) do botão que disparou. Testes: `apps/core/tests/test_js_confirm.py`.
- **Auditoria de consulta**: abrir a ficha de um eleitor grava `voter.view` (só o id). Nunca coloque dados pessoais em `details`.
- `seed_demo` só roda com `DEBUG=1` (ou `--force` / `ALLOW_SEED_DEMO=1`): ele cria contas com senha conhecida.
