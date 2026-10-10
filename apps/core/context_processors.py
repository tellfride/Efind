from .constants import Role
from .nav import build_nav


def panel(request):
    """Variáveis globais dos templates: campanha, permissões e menu lateral."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"base_layout": "layouts/public.html"}
    return {
        "base_layout": "layouts/shell.html",
        "campaign": getattr(request, "campaign", None),
        "perms": getattr(request, "perms", {}),
        "nav_sections": build_nav(user, getattr(request, "perms", {}), request.path),
        "is_super_admin": user.role == Role.SUPER_ADMIN,
        "is_campaign_admin": user.role == Role.ADMIN,
    }
