from django.urls import include, path

# Cada app define suas rotas com o caminho completo (ex.: "painel/eleitores/"), então todos entram na raiz.
urlpatterns = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.portal.urls")),
    path("", include("apps.voters.urls")),
    path("", include("apps.dashboards.urls")),
    path("", include("apps.team.urls")),
    path("", include("apps.mapview.urls")),
    path("", include("apps.messaging.urls")),
    path("", include("apps.whatsapp.urls")),
    path("", include("apps.superadmin.urls")),
    path("", include("apps.geo.urls")),
]

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
