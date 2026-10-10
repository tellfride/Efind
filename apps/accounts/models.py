from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from apps.core.constants import Role
from apps.core.crypto import random_invite_code
from apps.core.models import TimestampedModel
from apps.core.permissions import ACTIONS


class UserManager(BaseUserManager):
    use_in_migrations = True

    def unique_invite_code(self) -> str:
        while True:
            code = random_invite_code()
            if not self.model.objects.filter(invite_code=code).exists():
                return code

    def create_user(self, email: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("E-mail é obrigatório")
        extra.setdefault("invite_code", self.unique_invite_code())
        user = self.model(email=email.strip().lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("role", Role.SUPER_ADMIN)
        extra.setdefault("name", "Super Admin")
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, TimestampedModel):
    """Usuário do sistema. Hierarquia: ADMIN → COORDENADOR → CABO (parent aponta para o superior).
    SUPER_ADMIN pertence à plataforma (sem campanha)."""

    campaign = models.ForeignKey(
        "campaigns.Campaign", null=True, blank=True, on_delete=models.CASCADE, related_name="users"
    )
    name = models.CharField("nome", max_length=160)
    email = models.EmailField("e-mail", max_length=254, unique=True)
    phone = models.CharField("telefone", max_length=20, blank=True)  # 55DDNNNNNNNNN
    role = models.CharField("papel", max_length=12, choices=Role.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children", verbose_name="superior"
    )
    # Código do link/QR Code de cadastro de eleitores deste usuário
    invite_code = models.CharField(max_length=16, unique=True)
    is_active = models.BooleanField("ativo", default=True)
    goal = models.PositiveIntegerField("meta de cadastros", null=True, blank=True)
    region = models.CharField("região de atuação", max_length=120, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["campaign", "role"]), models.Index(fields=["parent"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role="SUPER_ADMIN", campaign__isnull=True)
                | (~models.Q(role="SUPER_ADMIN") & models.Q(campaign__isnull=False)),
                name="user_campaign_matches_role",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    # Não usamos o admin do Django nem permissões por objeto do Django
    def has_perm(self, perm, obj=None) -> bool:
        return False

    def has_module_perms(self, app_label) -> bool:
        return False

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN

    @property
    def is_campaign_admin(self) -> bool:
        return self.role == Role.ADMIN

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)


class RolePermission(TimestampedModel):
    """Permissões por papel dentro de uma campanha (definidas pelo ADMIN). ADMIN sempre tem acesso total."""

    campaign = models.ForeignKey("campaigns.Campaign", on_delete=models.CASCADE, related_name="role_permissions")
    role = models.CharField(max_length=12, choices=[(Role.COORDENADOR, "Coordenador"), (Role.CABO, "Cabo eleitoral")])
    module = models.CharField(max_length=30)
    can_view = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "role", "module"], name="uniq_role_permission")]

    def as_row(self) -> dict:
        return {"module": self.module, **{f"can_{a}": getattr(self, f"can_{a}") for a in ACTIONS}}


class UserPermission(TimestampedModel):
    """Exceções de permissão por usuário. None = herda do papel."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="permission_overrides")
    module = models.CharField(max_length=30)
    can_view = models.BooleanField(null=True, blank=True)
    can_create = models.BooleanField(null=True, blank=True)
    can_edit = models.BooleanField(null=True, blank=True)
    can_delete = models.BooleanField(null=True, blank=True)
    can_export = models.BooleanField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "module"], name="uniq_user_permission")]

    def as_row(self) -> dict:
        return {"module": self.module, **{f"can_{a}": getattr(self, f"can_{a}") for a in ACTIONS}}
