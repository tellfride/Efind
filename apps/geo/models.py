from django.db import models


class CepCache(models.Model):
    """Cache de consultas de CEP e geocodificação (compartilhado; não contém dados pessoais).
    A chave é o CEP (8 dígitos) ou "A:<uf>:<cidade>[:<bairro>]" para áreas."""

    key = models.CharField(max_length=120, primary_key=True)
    street = models.CharField(max_length=160, blank=True)
    neighborhood = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    # Origem das coordenadas: nominatim-rua | brasilapi | nominatim-cep | nominatim-bairro | nominatim-cidade | none
    geo_source = models.CharField(max_length=30, blank=True)
    # Caixa da área (bairro/cidade) como "sul,oeste,norte,leste" — usada para validar coordenadas
    bbox = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
