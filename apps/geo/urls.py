from django.urls import path

from . import views

app_name = "geo"

urlpatterns = [
    path("api/public/cep/<str:cep>/", views.cep_lookup, name="cep"),
]
