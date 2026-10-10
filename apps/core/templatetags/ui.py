"""Kit de UI para templates. Registrado como *builtin* (não precisa de {% load %}).

Filtros:  phone, cep, num, pct, brdate, brdatetime, initials, get_item, tags_list, role_label
Tags:     {% icon "users" "size-5 text-brand-600" %}   {% qs page=2 %}   {% badge "Ativo" "green" %}
          {% progress 40 100 "green" %}   {% avatar name %}   {% field form.name hint="..." %}
          {% stat_card "Eleitores" total icon="users-round" tone="brand" hint="..." %}
          {% pagination page_obj %}
Blocos:   {% page_header title="Eleitores" description="..." %}<botões>{% endpage_header %}
          {% card title="..." description="..." padding=False %}...{% endcard %}
          {% empty_state icon="inbox" title="Nada aqui" description="..." %}<botão>{% endempty_state %}
          {% alert "warning" title="Atenção" %}texto{% endalert %}
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

from django import template
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.core.constants import Role, label_of
from apps.core.phone import format_phone
from apps.core.utils import initials as _initials
from apps.core.utils import parse_tags

register = template.Library()

# ---------------------------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------------------------


@register.filter
def phone(value):
    return format_phone(value)


@register.filter
def cep(value):
    d = re.sub(r"\D", "", str(value or ""))
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (value or "")


@register.filter
def num(value):
    """1234567 → "1.234.567" """
    try:
        return f"{int(round(float(value))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


@register.filter
def pct(value, digits=1):
    """12.345 → "12,3%" """
    try:
        return f"{float(value):.{int(digits)}f}".replace(".", ",") + "%"
    except (TypeError, ValueError):
        return "0%"


@register.filter
def brdate(value):
    if not value:
        return "—"
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        value = timezone.localtime(value)
    return value.strftime("%d/%m/%Y")


@register.filter
def brdatetime(value):
    if not value:
        return "—"
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        value = timezone.localtime(value)
    return value.strftime("%d/%m/%Y %H:%M")


@register.filter
def initials(value):
    return _initials(value)


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def tags_list(value):
    return parse_tags(value)


@register.filter
def role_label(value):
    return label_of(Role, value)


@register.filter
def percent_of(value, total):
    try:
        return (float(value) / float(total)) * 100 if float(total) else 0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


# ---------------------------------------------------------------------------------------------
# Ícones (Lucide, arquivos em static/icons/)
# ---------------------------------------------------------------------------------------------

_ICON_DIR = Path(settings.BASE_DIR) / "static" / "icons"
_ICON_NAME = re.compile(r"^[a-z0-9-]+$")
_SVG_INNER = re.compile(r"<svg[^>]*>(.*)</svg>", re.DOTALL)
_icon_cache: dict[str, str] = {}


def _icon_inner(name: str) -> str:
    inner = _icon_cache.get(name)
    if inner is None:
        path = _ICON_DIR / f"{name}.svg"
        inner = ""
        if _ICON_NAME.match(name) and path.exists():
            m = _SVG_INNER.search(path.read_text(encoding="utf-8"))
            inner = m.group(1).strip() if m else ""
        _icon_cache[name] = inner
    return inner


@register.simple_tag
def icon(name: str, css: str = "size-4"):
    """Ícone Lucide inline. Para adicionar ícones: `node scripts/vendor.mjs --icon nome1 nome2`."""
    inner = _icon_inner(name)
    if not inner:
        inner = '<circle cx="12" cy="12" r="9"/>'  # ícone ausente: círculo
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="{}" aria-hidden="true">{}</svg>',
        css,
        mark_safe(inner),  # conteúdo vindo de arquivos do próprio projeto
    )


# ---------------------------------------------------------------------------------------------
# Querystring
# ---------------------------------------------------------------------------------------------


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Querystring atual com alterações: {% qs page=2 %}. Valor None/"" remove o parâmetro."""
    request = context["request"]
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = str(value)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag
def urlparams(**kwargs):
    """{% urlparams q="ana" page=2 %} → "q=ana&page=2" (ignora valores vazios)."""
    return urlencode({k: v for k, v in kwargs.items() if v not in (None, "")})


# ---------------------------------------------------------------------------------------------
# Componentes simples
# ---------------------------------------------------------------------------------------------

BADGE_TONES = {"gray", "brand", "green", "yellow", "red", "blue", "purple"}


@register.simple_tag
def badge(text, tone="gray", css=""):
    tone = tone if tone in BADGE_TONES else "gray"
    return format_html('<span class="badge badge-{} {}">{}</span>', tone, css, text)


@register.simple_tag
def progress(value, max_value=100, tone="brand"):
    try:
        pct_value = max(0.0, min(100.0, float(value) / float(max_value) * 100)) if float(max_value) else 0.0
    except (TypeError, ValueError):
        pct_value = 0.0
    tone = tone if tone in {"brand", "green", "yellow", "red"} else "brand"
    return format_html(
        '<div class="progress" role="progressbar" aria-valuenow="{}" aria-valuemin="0" aria-valuemax="100">'
        '<div class="progress-bar progress-{}" style="width:{}%"></div></div>',
        round(pct_value),
        tone,
        f"{pct_value:.1f}",
    )


@register.simple_tag
def avatar(name, css=""):
    return format_html('<span class="avatar {}" aria-hidden="true">{}</span>', css, _initials(name))


@register.inclusion_tag("components/stat_card.html")
def stat_card(label, value, icon="", tone="brand", hint="", href=""):
    return {"label": label, "value": value, "icon": icon, "tone": tone, "hint": hint, "href": href}


@register.inclusion_tag("components/field.html")
def field(bound_field, hint="", css="", label=None):
    """Rótulo + controle + dica/erro de um campo de formulário Django."""
    return {"field": bound_field, "hint": hint or bound_field.help_text, "css": css, "label": label}


@register.inclusion_tag("components/voter_filters.html", takes_context=True)
def voter_filters(context, filters, options, action="", fields=None, hide=None, expanded=False, submit_label="Filtrar"):
    """Painel de filtros de eleitores (formulário GET). Parâmetros de URL: veja apps.core.voter_filters.URL_PARAMS.
        {% voter_filters filters filter_options %}   (filters = parse_voter_filters(request.GET);
                                                       filter_options = get_voter_filter_options(request.user))
    `fields`/`hide`: listas de chaves (ex.: hide=["has_geo"]); `action`: URL de destino (padrão: a página atual)."""
    from apps.core.filter_options import build_filter_panel

    request = context["request"]
    panel = build_filter_panel(filters, options, fields, tuple(hide or ()), expanded)
    return {
        **panel,
        "filters": filters,
        "action": action or request.path,
        "clear_url": action or request.path,
        "submit_label": submit_label,
    }


@register.inclusion_tag("components/pagination.html", takes_context=True)
def pagination(context, page_obj):
    """Paginação (objeto Page do Django Paginator); preserva os demais parâmetros da URL."""
    return {"request": context["request"], "page_obj": page_obj}


# ---------------------------------------------------------------------------------------------
# Blocos (Django 5.2 simple_block_tag)
# ---------------------------------------------------------------------------------------------


@register.simple_block_tag
def page_header(content, title="", description=""):
    return render_to_string("components/page_header.html", {"title": title, "description": description, "actions": content})


@register.simple_block_tag
def card(content, title="", description="", padding=True, css=""):
    return render_to_string(
        "components/card.html",
        {"title": title, "description": description, "padding": padding, "css": css, "content": content},
    )


@register.simple_block_tag
def empty_state(content, title="", description="", icon="inbox"):
    return render_to_string(
        "components/empty_state.html", {"title": title, "description": description, "icon": icon, "action": content}
    )


@register.simple_block_tag
def alert(content, tone="info", title=""):
    tone = tone if tone in {"info", "success", "warning", "danger"} else "info"
    return render_to_string("components/alert.html", {"tone": tone, "title": title, "content": content})
