from django.urls import path

from . import views

app_name = "mapview"

urlpatterns = [
    path("painel/mapa/", views.index, name="index"),
    path("painel/mapa/localizar-pendentes/", views.geocode_pending, name="geocode_pending"),
    path("api/painel/mapa/dados/", views.data, name="data"),
]
