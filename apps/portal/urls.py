from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("favicon.ico", views.favicon, name="favicon"),
    path("privacidade/", views.privacy, name="privacy"),
    path("termos/", views.terms, name="terms"),
    path("painel/configuracoes/", views.settings_view, name="settings"),
    path("painel/auditoria/", views.audit_log, name="audit"),
    path("painel/auditoria/exportar/", views.audit_export, name="audit_export"),
]
