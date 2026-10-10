from django.urls import path

from . import permission_views, views

app_name = "team"

urlpatterns = [
    path("painel/equipe/", views.team_list, name="list"),
    path("painel/equipe/novo/", views.member_create, name="create"),
    path("painel/equipe/<uuid:member_id>/", views.member_detail, name="detail"),
    path("painel/equipe/<uuid:member_id>/editar/", views.member_update, name="update"),
    path("painel/equipe/<uuid:member_id>/mover/", views.member_move, name="move"),
    path("painel/equipe/<uuid:member_id>/ativar/", views.member_activate, name="activate"),
    path("painel/equipe/<uuid:member_id>/desativar/", views.member_deactivate, name="deactivate"),
    path("painel/equipe/<uuid:member_id>/redefinir-senha/", views.member_reset_password, name="reset_password"),
    path("painel/equipe/<uuid:member_id>/novo-link/", views.member_regenerate_link, name="regenerate_link"),
    path("painel/equipe/<uuid:member_id>/excluir/", views.member_delete, name="delete"),
    path("painel/permissoes/", permission_views.permissions, name="permissions"),
    path("painel/permissoes/papel/<slug:role_slug>/", permission_views.permissions_role_save, name="permissions_role_save"),
    path(
        "painel/permissoes/papel/<slug:role_slug>/restaurar/",
        permission_views.permissions_role_reset,
        name="permissions_role_reset",
    ),
    path("painel/permissoes/usuario/<uuid:user_id>/", permission_views.permissions_user_save, name="permissions_user_save"),
]
