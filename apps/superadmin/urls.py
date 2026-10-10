from django.urls import path

from . import views

app_name = "superadmin"

CAMPAIGN = "super/campanhas/<uuid:pk>/"

urlpatterns = [
    path("super/", views.home, name="home"),
    # Campanhas
    path("super/campanhas/", views.campaign_list, name="campaigns"),
    path("super/campanhas/nova/", views.campaign_create, name="campaign_create"),
    path(CAMPAIGN, views.campaign_detail, name="campaign_detail"),
    path(CAMPAIGN + "editar/", views.campaign_update, name="campaign_update"),
    path(CAMPAIGN + "suspender/", views.campaign_suspend, name="campaign_suspend"),
    path(CAMPAIGN + "reativar/", views.campaign_activate, name="campaign_activate"),
    path(CAMPAIGN + "excluir/", views.campaign_delete, name="campaign_delete"),
    # Administradores da campanha
    path(CAMPAIGN + "administradores/novo/", views.campaign_admin_create, name="campaign_admin_create"),
    path(
        CAMPAIGN + "administradores/<uuid:user_id>/senha/",
        views.campaign_admin_reset_password,
        name="campaign_admin_reset_password",
    ),
    path(
        CAMPAIGN + "administradores/<uuid:user_id>/ativar/",
        views.campaign_admin_set_active,
        {"active": True},
        name="campaign_admin_activate",
    ),
    path(
        CAMPAIGN + "administradores/<uuid:user_id>/desativar/",
        views.campaign_admin_set_active,
        {"active": False},
        name="campaign_admin_deactivate",
    ),
    # Super admins
    path("super/usuarios/", views.users, name="users"),
    path("super/usuarios/novo/", views.user_create, name="user_create"),
    path("super/usuarios/<uuid:user_id>/senha/", views.user_reset_password, name="user_reset_password"),
    path("super/usuarios/<uuid:user_id>/ativar/", views.user_set_active, {"active": True}, name="user_activate"),
    path("super/usuarios/<uuid:user_id>/desativar/", views.user_set_active, {"active": False}, name="user_deactivate"),
    # Auditoria
    path("super/auditoria/", views.audit_log, name="audit"),
]
