# E-Find

Sistema de gestão de campanha eleitoral: cadastro de eleitores por **link e QR Code**, equipe hierárquica com permissões,
**mapa por bairro** a partir do CEP, **dashboards** personalizáveis e **disparos de WhatsApp** (somente para quem consentiu).

> **Status:** em desenvolvimento. Funciona de ponta a ponta em ambiente local (SQLite) e passa em mais de 1.300 testes
> automatizados, mas **ainda não foi validado em um MariaDB de produção nem com contas reais dos provedores de WhatsApp**
> (veja "Limitações").

## Como funciona

```
Super admin  →  cria a campanha (candidato). Uma campanha nunca enxerga os dados de outra.
└── Administrador  →  controla tudo na campanha e define as permissões de cada papel
    └── Coordenador  →  vê a própria rede (ele + os cabos dele)
        └── Cabo eleitoral  →  vê só os eleitores que ele cadastrou
```

- **Cadastro:** cada usuário tem um link/QR Code próprio; todo eleitor fica vinculado a quem o cadastrou. O formulário público
  exige consentimento LGPD e oferece, em separado, o aceite para receber WhatsApp.
- **Painéis:** ranking de cadastros por cabo, metas, evolução por dia, bairros, perfil da base. Cada usuário vê os dados da sua rede.
- **Mapa:** bairros por CEP/geocodificação (BrasilAPI/ViaCEP/OpenStreetMap), com filtros.
- **WhatsApp:** apenas **APIs oficiais** (Meta Cloud API, Twilio, 360dialog) e um simulador para testes. Modelos de mensagem com
  variáveis, agendamento, fila com limite por minuto e descadastro automático ao responder "SAIR".
- **Segurança e LGPD:** isolamento entre campanhas e por hierarquia em toda consulta, credenciais de WhatsApp criptografadas
  (AES-256-GCM), trilha de auditoria sem dados pessoais, senhas provisórias com troca obrigatória, recuperação de senha por e-mail.

## Stack

Django 5.2 LTS · MariaDB (SQLite só para desenvolvimento) · Tailwind CSS v4 · HTMX · Alpine.js · Chart.js · Leaflet.
Todas as bibliotecas de front-end ficam em `static/` (sem CDN); **produção não precisa de Node**.

## Rodando localmente

Requisitos: Python 3.11+ (testado com 3.13).

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
cp .env.example .env                             # edite: DEBUG=1, SECRET_KEY, ENCRYPTION_KEY (comandos no próprio arquivo)
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo             # campanha de demonstração (só funciona com DEBUG=1)
.venv/bin/python manage.py runserver
```

Contas de demonstração (apenas desenvolvimento): `admin@demo.efind.com.br`, `coord1@demo.efind.com.br`,
`cabo1@demo.efind.com.br` (senha `Demo@2026`). O super admin usa o e-mail/senha definidos em `SEED_SUPERADMIN_*` no `.env`.

Para a fila de disparos e a geocodificação em segundo plano: `python manage.py run_worker` (outro terminal).

**Banco MariaDB:** passo a passo em [docs/MARIADB.md](docs/MARIADB.md). **Produção:** [docs/DEPLOY.md](docs/DEPLOY.md).

## Testes

```bash
python manage.py test apps                       # roda em SQLite em memória, sem rede
TEST_ON_MARIADB=1 python manage.py test apps     # opcional, no MariaDB configurado
```

Alterou classes Tailwind nos templates? `npm install && npm run build` recompila o CSS versionado em `static/css/app.css`.

## Documentação

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): estrutura, regras de segurança e isolamento, permissões, convenções e contratos entre módulos.
- [docs/MARIADB.md](docs/MARIADB.md) e [docs/DEPLOY.md](docs/DEPLOY.md): banco de dados e implantação.
- `legacy-nextjs/`: primeira versão (Next.js), arquivada apenas como referência; não faz parte do produto.

## Limitações

- Não validado em MariaDB real nem com Meta/Twilio/360dialog reais (testes usam SQLite e respostas simuladas).
- Interface conferida em navegador desktop e em 375 px, mas não em celulares reais nem no navegador interno do WhatsApp.
- Os textos de privacidade e termos de uso são genéricos: **exigem revisão jurídica** antes de uso real.
- O disparo em massa é restrito por desenho ao que a Res. TSE 23.610/2019 e a LGPD permitem: destinatários com consentimento,
  provedores oficiais e opção de descadastro. O uso lícito é responsabilidade de quem opera a campanha.

## Licença

Ainda não definida: até que o autor escolha uma licença, todos os direitos permanecem reservados.
