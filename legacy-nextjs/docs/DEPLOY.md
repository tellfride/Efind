# Implantação em produção (efind.com.br)

Guia para um servidor Linux (VPS) com Node.js 22+, PostgreSQL 15+, Nginx e PM2.
O sistema tem **dois processos**: o site (Next.js) e o **worker** (fila de disparos + geocodificação).

## 1. Banco de dados: trocar SQLite por PostgreSQL

O desenvolvimento usa SQLite. As migrations do Prisma são específicas de cada banco, então gere uma
linha de base para o Postgres uma única vez:

```bash
# prisma/schema.prisma
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}
```

```bash
rm -rf prisma/migrations
DATABASE_URL="postgresql://efind:SENHA@localhost:5432/efind" npx prisma migrate dev --name init
git add prisma && git commit -m "Migrations PostgreSQL"
```

> Buscas com `contains` são case-insensitive no SQLite, mas não no Postgres. Se quiser o mesmo
> comportamento, adicione `mode: "insensitive"` nas buscas por nome/e-mail de `src/server/access.ts`.

## 2. Variáveis de ambiente (`.env` no servidor)

Copie `.env.example` e preencha. Gere segredos novos — **nunca reutilize os do desenvolvimento**:

```bash
node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"  # SESSION_SECRET
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"     # ENCRYPTION_KEY
node -e "console.log(require('crypto').randomBytes(24).toString('base64url'))"  # CRON_SECRET
```

- `APP_URL` e `NEXT_PUBLIC_APP_URL` = `https://efind.com.br` (usados nos links/QR Codes e na URL do webhook).
- `ENCRYPTION_KEY` protege as credenciais das APIs de WhatsApp. Se for perdida, as conexões precisam ser recadastradas.

## 3. Build e primeira execução

```bash
npm ci
npx prisma migrate deploy
npm run db:seed          # cria o super admin (SEED_SUPERADMIN_EMAIL / SEED_SUPERADMIN_PASSWORD)
npm run build
```

O seed também cria uma **campanha de demonstração** (`demo`). Em produção, exclua-a pelo painel do
super admin (Campanhas → demo → Zona de perigo) ou rode o seed com um banco vazio e remova-a em seguida.

## 4. Processos com PM2

```bash
npm i -g pm2
pm2 start npm --name efind-web -- start
pm2 start npm --name efind-worker -- run worker
pm2 save && pm2 startup
```

Sem um processo persistente (ex.: Vercel), use um agendador externo chamando a cada minuto:

```bash
curl -fsS -H "Authorization: Bearer $CRON_SECRET" https://efind.com.br/api/cron/tick
```

## 5. Nginx + HTTPS

```nginx
server {
  server_name efind.com.br www.efind.com.br;
  client_max_body_size 6m;
  location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

```bash
sudo certbot --nginx -d efind.com.br -d www.efind.com.br
```

O cookie de sessão é `Secure` em produção — o site precisa estar em HTTPS.

## 6. WhatsApp (API oficial)

1. Em cada campanha: **Painel → WhatsApp → Conexão da API → Nova conexão**.
2. Para a Meta Cloud API, cadastre no app da Meta a URL de callback e o verify token exibidos no assistente
   e assine o campo `messages`.
3. Crie e aprove os templates no WhatsApp Manager e informe o nome do template aprovado em cada modelo de mensagem.
4. Respeite os limites de envio do seu número (tier) — ajuste "mensagens por minuto" na conexão.

## 7. Escala

- O limitador de taxa (login, formulário público) é em memória: com mais de uma instância web, troque
  `src/lib/rate-limit.ts` por Redis mantendo a mesma assinatura.
- Rode **um único worker** (o processador usa claims atômicos, mas um worker evita disputa desnecessária).
- Faça backup diário do Postgres (`pg_dump`) — os dados de eleitores são dados pessoais (LGPD).
