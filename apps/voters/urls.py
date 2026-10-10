from django.urls import path

from . import views_import, views_link, views_panel, views_public

app_name = "voters"

urlpatterns = [
    # Cadastro público pelo link/QR Code (sem login)
    path("c/<str:code>/", views_public.public_form, name="public_form"),
    path("c/<str:code>/obrigado/", views_public.public_thanks, name="public_thanks"),
    path("c/<str:code>/privacidade/", views_public.public_privacy, name="public_privacy"),
    # Meu link
    path("painel/meu-link/", views_link.my_link, name="my_link"),
    path("painel/meu-link/cartaz/", views_link.my_link_poster, name="my_link_poster"),
    # Eleitores
    path("painel/eleitores/", views_panel.voter_list, name="list"),
    path("painel/eleitores/novo/", views_panel.voter_create, name="create"),
    path("painel/eleitores/exportar/", views_panel.voter_export, name="export"),
    path("painel/eleitores/localizar-novamente/", views_panel.retry_geo, name="retry_geo"),
    path("painel/eleitores/importar/", views_import.voter_import, name="import"),
    path("painel/eleitores/importar/resultado/", views_import.voter_import_result, name="import_result"),
    path("api/painel/eleitores/importar/previa/", views_import.import_preview, name="import_preview"),
    path("painel/eleitores/<uuid:voter_id>/", views_panel.voter_detail, name="detail"),
    path("painel/eleitores/<uuid:voter_id>/editar/", views_panel.voter_edit, name="edit"),
    path("painel/eleitores/<uuid:voter_id>/descadastrar/", views_panel.voter_opt_out, name="opt_out"),
    path("painel/eleitores/<uuid:voter_id>/responsavel/", views_panel.voter_change_registrar, name="change_registrar"),
    path("painel/eleitores/<uuid:voter_id>/excluir/", views_panel.voter_delete, name="delete"),
]
