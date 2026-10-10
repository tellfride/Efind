# Banco de dados MariaDB

O E-Find usa **MariaDB** (testado com 12.1). Sem `DB_NAME` no `.env`, o sistema usa um SQLite local (`db.sqlite3`) —
apenas para desenvolvimento rápido. **Use MariaDB em desenvolvimento real e em produção.**

## 1. Criar o banco e um usuário próprio (uma vez)

Conecte como administrador do MariaDB (você digita a senha; ela não passa pelo chat):

```bash
"C:\Program Files\MariaDB 12.1\bin\mysql.exe" -u root -p
```

E execute (troque `SUA_SENHA_FORTE`):

```sql
CREATE DATABASE efind CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'efind'@'localhost' IDENTIFIED BY 'SUA_SENHA_FORTE';
GRANT ALL PRIVILEGES ON efind.* TO 'efind'@'localhost';
-- Para rodar os testes no MariaDB (opcional): o Django cria o banco test_efind
GRANT ALL PRIVILEGES ON `test\_efind`.* TO 'efind'@'localhost';
FLUSH PRIVILEGES;
```

> Nunca use o usuário `root` na aplicação. Em produção, restrinja o host do usuário (`'efind'@'10.0.0.%'`, etc.).

## 2. Configurar o `.env`

```ini
DB_NAME=efind
DB_USER=efind
DB_PASSWORD=SUA_SENHA_FORTE
DB_HOST=127.0.0.1
DB_PORT=3306
```

## 3. Criar as tabelas e os dados de demonstração

```bash
./.venv/Scripts/python.exe manage.py migrate
./.venv/Scripts/python.exe manage.py seed_demo
```

## Observações

- Colação `utf8mb4_unicode_ci`: buscas por nome/bairro ignoram maiúsculas **e acentos** ("sao paulo" encontra "São Paulo").
- Modo estrito (`STRICT_TRANS_TABLES`) e fuso UTC na conexão já são definidos pelo Django (`efind/settings.py`).
- Testes: `manage.py test` usa SQLite em memória. Para testar no MariaDB: `TEST_ON_MARIADB=1 manage.py test apps`.
- Backup: `mysqldump --single-transaction -u efind -p efind > backup.sql` (os dados são pessoais — LGPD).
