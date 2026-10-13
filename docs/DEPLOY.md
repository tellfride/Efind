# Implantação em produção (efind.com.br)

Servidor Linux (VPS) com Python 3.11+, MariaDB 10.6+ (testado com 12.1), Nginx e systemd. O sistema tem **dois processos**:
o site (gunicorn) e o **worker** (fila de disparos + geocodificação). O CSS já vem compilado em `static/css/app.css` —
**produção não precisa de Node**.

## 1. Banco de dados

Crie o banco e um usuário próprio (veja `docs/MARIADB.md`). Em produção, restrinja o host do usuário.

## 2. Código e ambiente

```bash
git clone <repositório> /srv/efind && cd /srv/efind
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env     # preencha (abaixo)
```

`.env` de produção — gere segredos **novos** (nunca reutilize os de desenvolvimento):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"                       # SECRET_KEY
python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"  # ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(24))"                       # CRON_SECRET
```

Obrigatórios: `DEBUG=0`, `SECRET_KEY`, `ENCRYPTION_KEY`, `ALLOWED_HOSTS=efind.com.br,www.efind.com.br`,
`APP_URL=https://efind.com.br`, `DB_*`. Com `APP_URL` em https o Django ativa redirecionamento HTTPS, cookies `Secure` e HSTS.
**Guarde a `ENCRYPTION_KEY`**: sem ela as credenciais de WhatsApp salvas não podem ser lidas (seria preciso recadastrar).

## 3. Preparar

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser --email voce@efind.com.br   # super admin da plataforma (pede nome? use --name via shell)
.venv/bin/python manage.py check --deploy
```

> **Não** rode `seed_demo` em produção (cria contas com senha conhecida). Crie as campanhas pelo painel do super admin.
> O primeiro super admin também pode ser criado por `python manage.py shell`:
> `User.objects.create_superuser("voce@efind.com.br", "senha-forte", name="Seu Nome")`.

## 4. Processos (systemd)

`/etc/systemd/system/efind-web.service`:

```ini
[Unit]
Description=E-Find (gunicorn)
After=network.target mariadb.service

[Service]
User=efind
WorkingDirectory=/srv/efind
EnvironmentFile=/srv/efind/.env
ExecStart=/srv/efind/.venv/bin/gunicorn efind.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/efind-worker.service` (rode **uma** instância):

```ini
[Unit]
Description=E-Find worker (fila de disparos e geocodificação)
After=network.target mariadb.service

[Service]
User=efind
WorkingDirectory=/srv/efind
EnvironmentFile=/srv/efind/.env
ExecStart=/srv/efind/.venv/bin/python manage.py run_worker
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now efind-web efind-worker
```

Sem processo persistente (ex.: hospedagem sem worker), use um agendador chamando a cada minuto:
`curl -fsS -H "Authorization: Bearer $CRON_SECRET" https://efind.com.br/api/cron/tick/` (prefira o cabeçalho; `?secret=` aparece em logs).

## 5. Nginx + HTTPS

```nginx
server {
  server_name efind.com.br www.efind.com.br;
  client_max_body_size 6m;
  location /static/ { alias /srv/efind/staticfiles/; expires 30d; }
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

```bash
sudo certbot --nginx -d efind.com.br -d www.efind.com.br
```

O `X-Forwarded-Proto` é obrigatório (o Django decide HTTPS por ele). O IP do cliente (limites de taxa, consentimento) vem de
`X-Forwarded-For` apenas quando o site roda atrás de HTTPS configurado; mantenha o Nginx como único acesso ao gunicorn.

## 6. WhatsApp (API oficial)

1. Por campanha: **Painel → Conexão da API → Nova conexão** (assistente em 4 etapas; testa a conexão e mostra a URL do webhook).
2. Meta Cloud API: cadastre no app da Meta a **URL de callback** e o **verify token** exibidos e assine o campo `messages`;
   informe o **App Secret** para validar a assinatura dos webhooks.
3. Crie e aprove os templates no WhatsApp Manager; informe o nome do template aprovado em cada modelo de mensagem
   (mensagens iniciadas pela empresa exigem template aprovado).
4. Respeite o limite do número (tier) ajustando "mensagens por minuto" na conexão.

## 7. Escala e operação

- Limitadores de taxa (login, cadastro público, CEP) usam o cache local do processo. Com mais de um processo/servidor web,
  configure `CACHES` com Redis/Memcached em `efind/settings.py` (a API de `apps.core.ratelimit` não muda).
- Rode **um único worker** (as reservas de mensagens são atômicas, mas um worker evita disputa desnecessária).
- Backups diários do MariaDB (`mysqldump --single-transaction`): os dados de eleitores são dados pessoais (LGPD).
- Logs não contêm dados pessoais por regra do projeto; mantenha o acesso ao banco e aos backups restrito.
- Textos de privacidade e termos de uso são genéricos: **passe por revisão jurídica** antes de publicar.

## 8. E-mail e recuperação de senha

O "Esqueci minha senha" só aparece quando há e-mail configurado. Preencha no `.env` (SMTP do seu provedor: Amazon SES, SendGrid, Mailgun, Zoho, o SMTP da hospedagem...):

```ini
EMAIL_HOST=smtp.seudominio.com
EMAIL_PORT=587
EMAIL_HOST_USER=usuario
EMAIL_HOST_PASSWORD=senha
EMAIL_USE_TLS=1
DEFAULT_FROM_EMAIL=E-Find <nao-responda@efind.com.br>
```

- Os links valem 1 hora e são de uso único; o endereço do link vem de `APP_URL` (não do cabeçalho `Host`).
- A resposta é a mesma exista ou não a conta (não revela quem está cadastrado); há limite de 3 pedidos por e-mail e 10 por IP a cada hora.
- Configure SPF/DKIM do domínio de envio para os e-mails não caírem no spam.
- Senhas provisórias geradas por administradores (equipe, super admin) exigem troca no primeiro acesso.

## 9. Atualizando uma instalação existente

```bash
git pull
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart efind-web efind-worker
```

**Eleitores com localização errada no mapa** (versões anteriores aceitavam coordenadas de fontes externas sem conferir o bairro):
refaça a localização com as regras novas, que só aceitam pontos dentro do bairro do eleitor:

```bash
.venv/bin/python manage.py regeocode --campaign SLUG --all --purge-cache   # uma campanha
.venv/bin/python manage.py regeocode --all --purge-cache                   # todas
```

O comando respeita o limite de 1 consulta por segundo do OpenStreetMap (os resultados ficam em cache por CEP e bairro). Também há o
botão **Relocalizar todos os eleitores** no mapa (administrador), que devolve todos à fila do worker.
