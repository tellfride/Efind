from django.urls import path

from . import views, webhook_views

app_name = "whatsapp"

urlpatterns = [
    # Painel (lista usada pelo menu lateral: /painel/whatsapp/)
    path("painel/whatsapp/", views.connections, name="connections"),
    path("painel/whatsapp/nova/", views.connection_new, name="connection_new"),
    path("painel/whatsapp/<uuid:pk>/editar/", views.connection_edit, name="connection_edit"),
    path("painel/whatsapp/<uuid:pk>/webhook/", views.connection_webhook, name="connection_webhook"),
    path("painel/whatsapp/<uuid:pk>/teste/", views.connection_check, name="connection_check"),
    # Ações (somente POST + redirect)
    path("painel/whatsapp/<uuid:pk>/testar/", views.connection_test, name="connection_test"),
    path("painel/whatsapp/<uuid:pk>/padrao/", views.connection_default, name="connection_default"),
    path("painel/whatsapp/<uuid:pk>/desativar/", views.connection_disable, name="connection_disable"),
    path("painel/whatsapp/<uuid:pk>/ativar/", views.connection_enable, name="connection_enable"),
    path("painel/whatsapp/<uuid:pk>/excluir/", views.connection_delete, name="connection_delete"),
    # JSON (assistente de conexão)
    path("api/painel/whatsapp/<uuid:pk>/testar/", views.api_test_connection, name="api_test_connection"),
    path("api/painel/whatsapp/<uuid:pk>/mensagem-teste/", views.api_send_test_message, name="api_send_test_message"),
    path("api/painel/whatsapp/<uuid:pk>/registrar-webhook/", views.api_register_webhook, name="api_register_webhook"),
    # Webhook público dos provedores (sem login/CSRF; autenticado pelo token na URL + assinatura)
    path("api/webhooks/whatsapp/<str:token>/", webhook_views.webhook, name="webhook"),
]
