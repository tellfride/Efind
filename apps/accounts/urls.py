from django.contrib.auth import views as auth_views
from django.urls import path

from . import password_reset, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("painel/perfil/", views.panel_profile, name="profile"),
    path("super/perfil/", views.super_profile, name="super_profile"),
    # Recuperação de senha por e-mail (só com e-mail configurado: settings.PASSWORD_RESET_ENABLED)
    path("senha/esqueci/", password_reset.RequestPasswordResetView.as_view(), name="password_reset"),
    path(
        "senha/esqueci/enviado/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path("senha/redefinir/<uidb64>/<token>/", password_reset.ConfirmPasswordResetView.as_view(), name="password_reset_confirm"),
    path(
        "senha/redefinir/concluido/",
        auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"),
        name="password_reset_complete",
    ),
]
