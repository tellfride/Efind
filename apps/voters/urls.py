from django.urls import path, re_path
from django.views.generic import RedirectView

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
    # Apoiadores
    path("painel/apoiadores/", views_panel.voter_list, name="list"),
    path("painel/apoiadores/novo/", views_panel.voter_create, name="create"),
    path("painel/apoiadores/exportar/", views_panel.voter_export, name="export"),
    path("painel/apoiadores/localizar-novamente/", views_panel.retry_geo, name="retry_geo"),
    path("painel/apoiadores/importar/", views_import.voter_import, name="import"),
    path("painel/apoiadores/importar/modelo/", views_import.import_template, name="import_template"),
    path("painel/apoiadores/importar/resultado/", views_import.voter_import_result, name="import_result"),
    path("api/painel/apoiadores/importar/previa/", views_import.import_preview, name="import_preview"),
    path("painel/apoiadores/<uuid:voter_id>/", views_panel.voter_detail, name="detail"),
    path("painel/apoiadores/<uuid:voter_id>/editar/", views_panel.voter_edit, name="edit"),
    path("painel/apoiadores/<uuid:voter_id>/descadastrar/", views_panel.voter_opt_out, name="opt_out"),
    path("painel/apoiadores/<uuid:voter_id>/responsavel/", views_panel.voter_change_registrar, name="change_registrar"),
    path("painel/apoiadores/<uuid:voter_id>/excluir/", views_panel.voter_delete, name="delete"),
    # Endereços antigos (antes de "eleitores" virar "apoiadores"): favoritos e links já enviados continuam funcionando
    re_path(
        r"^painel/eleitores/(?P<rest>.*)$",
        RedirectView.as_view(url="/painel/apoiadores/%(rest)s", permanent=True, query_string=True),
        name="legacy_redirect",
    ),
]
