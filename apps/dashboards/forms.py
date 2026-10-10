"""Formulários dos dashboards."""

from __future__ import annotations

from django import forms

from apps.core.forms import StyledFormMixin

from .presets import DASHBOARD_PRESET_KEYS
from .services import BLANK_PRESET

NAME_MAX = 80
DESCRIPTION_MAX = 300


def _clean_name(value: str) -> str:
    return " ".join((value or "").split())


class DashboardCreateForm(StyledFormMixin, forms.Form):
    """Novo dashboard: nome, descrição e ponto de partida (um dos modelos ou em branco)."""

    name = forms.CharField(label="Nome", min_length=2, max_length=NAME_MAX, widget=forms.TextInput(attrs={"autofocus": True}))
    description = forms.CharField(
        label="Descrição",
        required=False,
        max_length=DESCRIPTION_MAX,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Opcional. Ajuda a equipe a entender o objetivo do painel.",
    )
    preset = forms.ChoiceField(
        label="Ponto de partida",
        choices=[(BLANK_PRESET, "Em branco"), *[(k, k) for k in DASHBOARD_PRESET_KEYS]],
        initial=DASHBOARD_PRESET_KEYS[0],
        widget=forms.RadioSelect,
        error_messages={"invalid_choice": "Escolha um ponto de partida válido."},
    )

    def clean_name(self):
        return _clean_name(self.cleaned_data["name"])

    def clean_description(self):
        return _clean_name(self.cleaned_data.get("description", ""))


class DashboardSaveForm(forms.Form):
    """Campos do dashboard enviados pelo montador (os widgets são validados à parte por `validate_widgets`)."""

    name = forms.CharField(
        min_length=2,
        max_length=NAME_MAX,
        error_messages={
            "required": "Informe o nome do dashboard.",
            "min_length": "O nome deve ter pelo menos 2 caracteres.",
            "max_length": f"O nome pode ter no máximo {NAME_MAX} caracteres.",
        },
    )
    description = forms.CharField(
        required=False,
        max_length=DESCRIPTION_MAX,
        error_messages={"max_length": f"A descrição pode ter no máximo {DESCRIPTION_MAX} caracteres."},
    )
    shared = forms.BooleanField(required=False)
    campaign_default = forms.BooleanField(required=False)

    def clean_name(self):
        return _clean_name(self.cleaned_data["name"])

    def clean_description(self):
        return _clean_name(self.cleaned_data.get("description", ""))

    def first_error(self) -> str:
        for errors in self.errors.values():
            if errors:
                return str(errors[0])
        return "Dados inválidos."
