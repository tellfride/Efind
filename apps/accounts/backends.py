from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError


class EmailBackend(ModelBackend):
    """Login por e-mail (sem diferenciar maiúsculas). Carrega a campanha junto com o usuário."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (username or kwargs.get("email") or "").strip().lower()
        return super().authenticate(request, username=email, password=password)

    def get_user(self, user_id):
        User = get_user_model()
        try:
            user = User._default_manager.select_related("campaign").get(pk=user_id)
        except (User.DoesNotExist, ValidationError, ValueError, TypeError):
            return None
        return user if self.user_can_authenticate(user) else None
