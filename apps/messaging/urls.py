from django.urls import path

from . import views_api, views_broadcasts, views_templates

app_name = "messaging"

urlpatterns = [
    # Modelos de mensagem
    path("painel/mensagens/modelos/", views_templates.template_list, name="templates"),
    path("painel/mensagens/modelos/novo/", views_templates.template_create, name="template_create"),
    path("painel/mensagens/modelos/<uuid:pk>/", views_templates.template_edit, name="template_edit"),
    path("painel/mensagens/modelos/<uuid:pk>/duplicar/", views_templates.template_duplicate, name="template_duplicate"),
    path("painel/mensagens/modelos/<uuid:pk>/excluir/", views_templates.template_delete, name="template_delete"),
    # Disparos
    path("painel/mensagens/disparos/", views_broadcasts.broadcast_list, name="broadcasts"),
    path("painel/mensagens/disparos/novo/", views_broadcasts.broadcast_new, name="broadcast_new"),
    path("painel/mensagens/disparos/<uuid:pk>/", views_broadcasts.broadcast_detail, name="broadcast_detail"),
    path(
        "painel/mensagens/disparos/<uuid:pk>/acao/<str:control>/",
        views_broadcasts.broadcast_control,
        name="broadcast_control",
    ),
    path("painel/mensagens/disparos/<uuid:pk>/excluir/", views_broadcasts.broadcast_delete, name="broadcast_delete"),
    path(
        "painel/mensagens/disparos/<uuid:pk>/processar/",
        views_broadcasts.broadcast_process_now,
        name="broadcast_process_now",
    ),
    # API (JSON) e automação
    path("api/painel/disparos/publico/", views_api.audience_api, name="audience"),
    path("api/cron/tick/", views_api.cron_tick, name="cron_tick"),
]
