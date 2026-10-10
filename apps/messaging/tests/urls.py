"""URLconf isolado dos testes do módulo (não depende de erros temporários em outros módulos)."""

from django.urls import include, path

urlpatterns = [path("", include("apps.messaging.urls"))]

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
