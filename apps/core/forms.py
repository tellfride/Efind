"""Base para formulários: aplica as classes CSS do kit de UI (input/select/textarea/checkbox) aos widgets
e normaliza campos comuns (telefone, CEP, e-mail)."""

from __future__ import annotations

from django import forms

from .phone import normalize_br_phone

_INPUT_WIDGETS = (
    forms.TextInput,
    forms.EmailInput,
    forms.NumberInput,
    forms.PasswordInput,
    forms.URLInput,
    forms.DateInput,
    forms.DateTimeInput,
    forms.TimeInput,
    forms.FileInput,
    forms.ColorInput if hasattr(forms, "ColorInput") else forms.TextInput,
)


def style_widget(widget: forms.Widget) -> None:
    """Acrescenta a classe CSS semântica do kit ao widget (idempotente)."""
    if isinstance(widget, forms.CheckboxInput):
        css = "checkbox"
    elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
        css = "select"
    elif isinstance(widget, forms.Textarea):
        css = "textarea"
    elif isinstance(widget, (forms.RadioSelect, forms.CheckboxSelectMultiple, forms.HiddenInput)):
        return
    elif isinstance(widget, _INPUT_WIDGETS):
        css = "input"
    else:
        css = "input"
    existing = widget.attrs.get("class", "")
    if css not in existing.split():
        widget.attrs["class"] = f"{existing} {css}".strip()


class StyledFormMixin:
    """Use: class MeuForm(StyledFormMixin, forms.Form). Também marca aria-invalid nos campos com erro."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            style_widget(field.widget)
            if field.required and not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("required", "required")

    def full_clean(self):
        super().full_clean()
        if self.is_bound:
            for name in self.errors:
                if name in self.fields:
                    self.fields[name].widget.attrs["aria-invalid"] = "true"


class PhoneField(forms.CharField):
    """Telefone brasileiro: aceita máscara, devolve só dígitos com DDI (55DDNNNNNNNNN)."""

    default_error_messages = {"invalid": "Informe um telefone válido com DDD, ex.: (11) 98765-4321."}

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 25)
        super().__init__(*args, **kwargs)
        self.widget.attrs.setdefault("inputmode", "tel")
        self.widget.attrs.setdefault("placeholder", "(11) 98765-4321")
        self.widget.attrs.setdefault("data-mask", "phone")

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return ""
        normalized = normalize_br_phone(value)
        if normalized is None:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        return normalized

    def prepare_value(self, value):
        from .phone import format_phone

        return format_phone(value) if value else value
