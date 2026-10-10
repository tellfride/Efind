# E-Find

Sistema de gestão de campanha eleitoral — **Django 5.2 + MariaDB + Tailwind/HTMX/Alpine**. **Leia `docs/ARCHITECTURE.md`
antes de alterar código**: ele define a hierarquia, as regras de isolamento entre campanhas, o modelo de permissões, as
convenções e os contratos entre módulos. `legacy-nextjs/` é uma versão antiga arquivada (só referência).

Regras essenciais:
- Interface em português do Brasil; identificadores de código em inglês; mobile-first (360 px).
- Toda view de painel começa com um decorator de `apps/core/decorators.py`; toda leitura/escrita de eleitores/equipe
  passa pelos helpers de escopo de `apps/core/access.py`. Nunca confie em ids vindos do cliente sem validar campanha e escopo.
- Disparos de WhatsApp somente para eleitores com consentimento (`MESSAGEABLE_Q`) e somente por provedores oficiais
  (Meta Cloud API, Twilio, 360dialog) ou o simulador.
- Use o kit de UI (`templates/components/`, `apps/core/templatetags/ui.py`, classes de `assets/css/app.css`) e o componente
  `{% voter_filters %}`. Nunca edite `static/css/app.css` à mão (`npm run build:css`).
- Models/migrations são da fundação; módulos não os alteram sem alinhar.
- Python do projeto: `./.venv/Scripts/python.exe` (Windows). Verificação: `manage.py check`, `manage.py test apps`.
- Não coloque segredos no código nem no chat; credenciais ficam no `.env` (não versionado).
