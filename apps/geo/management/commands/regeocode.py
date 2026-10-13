"""Relocaliza eleitores pelo CEP/bairro, validando cada ponto dentro do bairro. Corrige coordenadas erradas gravadas
por versões anteriores (ex.: eleitor de Guadalupe aparecendo no Centro do Rio).

    python manage.py regeocode --campaign demo --all     # refaz TODOS os eleitores com endereço de uma campanha
    python manage.py regeocode --all                     # idem, todas as campanhas
    python manage.py regeocode                           # só os pendentes e os que falharam
    python manage.py regeocode --all --purge-cache       # também descarta o cache de pontos e áreas (força nova consulta)

Respeita o limite de 1 requisição por segundo do Nominatim; os resultados ficam em cache por CEP+bairro, então
eleitores da mesma rua/bairro não geram novas consultas.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from apps.campaigns.models import Campaign
from apps.core.constants import GeoStatus
from apps.geo.geocode import process_pending_geocoding
from apps.geo.models import CepCache
from apps.voters.models import Voter

BATCH = 20


class Command(BaseCommand):
    help = "Relocaliza eleitores pelo CEP/bairro, validando o ponto dentro do bairro (corrige coordenadas erradas)."

    def add_arguments(self, parser):
        parser.add_argument("--campaign", help="slug da campanha (padrão: todas)")
        parser.add_argument("--all", action="store_true", help="refaz TODOS os eleitores com endereço, não só os pendentes")
        parser.add_argument("--purge-cache", action="store_true", help="descarta o cache de pontos e áreas antes de começar")
        parser.add_argument("--limit", type=int, default=0, help="máximo de eleitores a processar (0 = sem limite)")

    def handle(self, *args, **opts):
        campaign_id = None
        if opts["campaign"]:
            campaign = Campaign.objects.filter(slug=opts["campaign"]).first()
            if campaign is None:
                raise CommandError(f"Campanha '{opts['campaign']}' não encontrada.")
            campaign_id = campaign.pk

        voters = Voter.objects.exclude(city="", cep="")  # sem CEP nem cidade não há o que localizar
        if campaign_id is not None:
            voters = voters.filter(campaign_id=campaign_id)

        if opts["purge_cache"]:
            # só o cache de pontos (P:/S:) e áreas (A:); as linhas de CEP (8 dígitos) são endereços e continuam valendo
            removed, _ = CepCache.objects.filter(
                Q(key__startswith="P:") | Q(key__startswith="S:") | Q(key__startswith="A:")
            ).delete()
            self.stdout.write(f"Cache de geocodificação descartado ({removed} entradas).")

        if opts["all"]:
            voters.update(geo_status=GeoStatus.PENDING)
        else:
            voters.filter(geo_status=GeoStatus.FAILED).update(geo_status=GeoStatus.PENDING)

        total = voters.filter(geo_status=GeoStatus.PENDING).count()
        if not total:
            self.stdout.write("Nada a processar.")
            return
        limit = opts["limit"] or total
        self.stdout.write(f"Relocalizando {min(limit, total)} de {total} eleitores (até 1 consulta por segundo)...")

        done, started = 0, time.monotonic()
        while done < limit:
            n = process_pending_geocoding(limit=min(BATCH, limit - done), campaign_id=campaign_id)
            if n == 0:
                break
            done += n
            self.stdout.write(f"  {done}/{min(limit, total)} ({time.monotonic() - started:.0f} s)")

        summary = {
            row["geo_status"]: row["n"]
            for row in voters.order_by().values("geo_status").annotate(n=Count("id"))
        }
        self.stdout.write(
            self.style.SUCCESS(
                f"Concluído: {summary.get(GeoStatus.OK, 0)} localizados na rua, "
                f"{summary.get(GeoStatus.APPROXIMATE, 0)} aproximados (centro do bairro/cidade), "
                f"{summary.get(GeoStatus.FAILED, 0)} sem localização, "
                f"{summary.get(GeoStatus.PENDING, 0)} ainda na fila."
            )
        )
