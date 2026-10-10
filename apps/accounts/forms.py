from django import forms
from django.contrib.auth import password_validation

from apps.core.forms import PhoneField, StyledFormMixin


class LoginForm(StyledFormMixin, forms.Form):
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "voce@campanha.com.br", "autofocus": True}),
    )
    password = forms.CharField(label="Senha", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    next = forms.CharField(required=False, widget=forms.HiddenInput)


class ProfileForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Nome", min_length=3, max_length=160)
    phone = PhoneField(label="Telefone / WhatsApp", required=False)


class ChangePasswordForm(StyledFormMixin, forms.Form):
    current_password = forms.CharField(
        label="Senha atual", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )
    new_password = forms.CharField(
        label="Nova senha",
        help_text="Mínimo de 8 caracteres, com letras e números.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        label="Confirmar nova senha", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if self.user is None or not self.user.check_password(value):
            raise forms.ValidationError("Senha atual incorreta.")
        return value

    def clean_new_password(self):
        value = self.cleaned_data["new_password"]
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise forms.ValidationError("A senha deve conter letras e números.")
        password_validation.validate_password(value, self.user)
        return value

    def clean(self):
        data = super().clean()
        if data.get("new_password") and data.get("confirm_password") and data["new_password"] != data["confirm_password"]:
            self.add_error("confirm_password", "As senhas não conferem.")
        return data
