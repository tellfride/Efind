from django.db import migrations
from django.db.models import Q


def requeue_geocoding(apps, schema_editor):
    """Versões anteriores aceitavam as coordenadas do BrasilAPI sem conferir o bairro (todos os CEPs de uma avenida longa
    caíam no mesmo ponto, ex.: Guadalupe no Centro do Rio). Devolve os apoiadores com endereço à fila do worker, que os
    localiza de novo com as regras novas; os pontos antigos continuam no mapa até o novo resultado chegar.
    Também descarta o cache de áreas e pontos da versão anterior (inclusive buscas que tinham falhado)."""
    Voter = apps.get_model("voters", "Voter")
    CepCache = apps.get_model("geo", "CepCache")
    Voter.objects.exclude(city="", cep="").update(geo_status="PENDING")
    CepCache.objects.filter(Q(key__startswith="P:") | Q(key__startswith="S:") | Q(key__startswith="A:")).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("geo", "0002_cepcache_bbox"),
        ("voters", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(requeue_geocoding, migrations.RunPython.noop),
    ]
