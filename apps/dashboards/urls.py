from django.urls import path

from . import views

app_name = "dashboards"

urlpatterns = [
    path("painel/", views.home, name="home"),
    path("painel/dashboards/", views.dashboard_list, name="list"),
    path("painel/dashboards/novo/", views.create, name="create"),
    path("painel/dashboards/padroes/", views.create_defaults, name="create_defaults"),
    path("painel/dashboards/<uuid:pk>/", views.detail, name="detail"),
    path("painel/dashboards/<uuid:pk>/editar/", views.edit, name="edit"),
    path("painel/dashboards/<uuid:pk>/duplicar/", views.duplicate, name="duplicate"),
    path("painel/dashboards/<uuid:pk>/padrao/", views.toggle_default, name="toggle_default"),
    path("painel/dashboards/<uuid:pk>/excluir/", views.delete, name="delete"),
    # API (JSON) usada pelo JS dos dashboards
    path("api/painel/dashboard/data/", views.data, name="data"),
    path("api/painel/dashboard/filtros/", views.filters_panel, name="filters"),
    path("api/painel/dashboard/<uuid:pk>/salvar/", views.save, name="save"),
]
