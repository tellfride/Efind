"""URLconf isolado dos testes do módulo (não depende de erros temporários em outros módulos)."""

from django.urls import include, path

urlpatterns = [path("", include("apps.voters.urls"))]
