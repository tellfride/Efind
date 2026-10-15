"""Seed de desenvolvimento: super admin + campanha de demonstração com equipe, apoiadores e modelos fictícios.

    python manage.py seed_demo            # idempotente (não duplica)
    python manage.py seed_demo --reset    # apaga a campanha "demo" e recria

NUNCA use em produção: cria contas com senha conhecida.
"""

from __future__ import annotations

import datetime as dt
import os
import random

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.constants import GeoStatus, Role
from apps.core.crypto import encrypt_json, random_token
from apps.core.utils import serialize_tags
from apps.messaging.models import MessageTemplate
from apps.voters.models import Voter
from apps.whatsapp.models import WhatsAppConnection

DEMO_PASSWORD = "Demo@2026"

# Bairros de Campinas/SP com coordenadas aproximadas (centro do bairro)
BAIRROS = [
    ("Centro", -22.9056, -47.0608, "13010"),
    ("Cambuí", -22.8937, -47.0508, "13024"),
    ("Taquaral", -22.8735, -47.0544, "13076"),
    ("Barão Geraldo", -22.8166, -47.0846, "13084"),
    ("Sousas", -22.8806, -46.9706, "13105"),
    ("Jardim Proença", -22.9137, -47.0469, "13026"),
    ("Botafogo", -22.8996, -47.0707, "13020"),
    ("Vila Industrial", -22.9175, -47.0744, "13035"),
    ("Campos Elíseos", -22.9275, -47.0931, "13060"),
    ("Jardim do Lago", -22.9318, -47.1025, "13050"),
    ("Ouro Verde", -22.9839, -47.1305, "13056"),
    ("Nova Campinas", -22.8972, -47.0425, "13092"),
]
NOMES = "Ana Bruno Carla Diego Eduarda Felipe Gabriela Henrique Isabela João Larissa Marcos Natália Otávio Paula Rafael Sabrina Thiago Vanessa Wagner Yasmin Lucas Mariana Pedro Beatriz Gustavo Camila Rodrigo Juliana André".split()
SOBRENOMES = "Silva Santos Oliveira Souza Lima Pereira Costa Ferreira Almeida Ribeiro Carvalho Gomes Martins Araújo Barbosa Rocha".split()
RUAS = ["Rua das Flores", "Av. Brasil", "Rua José Paulino", "Rua Barão de Jaguara", "Av. Norte-Sul", "Rua Coronel Quirino", "Rua Maria Monteiro", "Av. Orosimbo Maia"]
APOIO = ["APOIADOR", "APOIADOR", "SIMPATIZANTE", "SIMPATIZANTE", "INDECISO", ""]
TAGS = ["saude", "educacao", "jovem", "idoso", "comerciante", "igreja", "esporte"]


class Command(BaseCommand):
    help = "Cria o super admin e uma campanha de demonstração (somente desenvolvimento)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Apaga a campanha demo e recria")
        parser.add_argument("--voters", type=int, default=240, help="Quantidade de apoiadores fictícios")
        parser.add_argument("--force", action="store_true", help="Permite rodar com DEBUG desligado (NÃO use em produção)")

    def handle(self, *args, **opts):
        if not (settings.DEBUG or opts["force"] or os.environ.get("ALLOW_SEED_DEMO") == "1"):
            raise CommandError(
                "seed_demo cria contas com senha conhecida e só deve rodar em desenvolvimento (DEBUG=1). "
                "Em produção crie campanhas pelo painel do super admin."
            )
        super_email = os.environ.get("SEED_SUPERADMIN_EMAIL", "super@efind.com.br").strip().lower()
        super_password = os.environ.get("SEED_SUPERADMIN_PASSWORD", "")
        if not super_password:
            raise CommandError("Defina SEED_SUPERADMIN_PASSWORD no .env")

        if not User.objects.filter(email=super_email).exists():
            User.objects.create_superuser(super_email, super_password, name="Super Admin E-Find")
            self.stdout.write(self.style.SUCCESS(f"Super admin criado: {super_email}"))

        existing = Campaign.objects.filter(slug="demo").first()
        if existing and not opts["reset"]:
            self.stdout.write("Campanha demo já existe — nada a fazer (use --reset para recriar).")
            return
        if existing:
            with transaction.atomic():
                Voter.objects.filter(campaign=existing).delete()
                existing.delete()

        rng = random.Random(42)
        pick = rng.choice
        now = timezone.now()

        with transaction.atomic():
            campaign = Campaign.objects.create(
                slug="demo",
                candidate_name="João Carlos Demonstração",
                ballot_name="Dr. João Demo",
                ballot_number="12345",
                party="PDEMO",
                office="VEREADOR",
                city="Campinas",
                state="SP",
                election_year=2026,
                voter_goal=5000,
                form_title="Faça parte da nossa campanha!",
                form_message="Cadastre-se para receber novidades e participar das ações no seu bairro.",
                privacy_contact="privacidade@demo.efind.com.br",
            )
            bootstrap_campaign(campaign)

            admin = User.objects.create_user(
                "admin@demo.efind.com.br", DEMO_PASSWORD, name="Admin Demo", role=Role.ADMIN, campaign=campaign
            )
            coords = [
                User.objects.create_user(
                    f"coord{i + 1}@demo.efind.com.br",
                    DEMO_PASSWORD,
                    name=name,
                    role=Role.COORDENADOR,
                    campaign=campaign,
                    parent=admin,
                    goal=800,
                    region="Região Norte" if i == 0 else "Região Sul",
                )
                for i, name in enumerate(["Coordenadora Fernanda", "Coordenador Ricardo"])
            ]
            cabos = [
                User.objects.create_user(
                    f"cabo{i + 1}@demo.efind.com.br",
                    DEMO_PASSWORD,
                    name=name,
                    role=Role.CABO,
                    campaign=campaign,
                    parent=coords[i % 2],
                    goal=150,
                    phone=f"55199{81000000 + i * 1111:08d}",
                )
                for i, name in enumerate(["Cabo Paulo", "Cabo Renata", "Cabo Sérgio", "Cabo Tatiane", "Cabo Valter"])
            ]

            registrars = [*cabos, *cabos, *cabos, *coords, admin]
            used: set[str] = set()
            voters = []
            for _ in range(opts["voters"]):
                hood, lat, lng, cep = pick(BAIRROS)
                name = f"{pick(NOMES)} {pick(SOBRENOMES)} {pick(SOBRENOMES)}"
                while True:
                    phone = f"55199{rng.randrange(10**8):08d}"
                    if phone not in used:
                        used.add(phone)
                        break
                created = now - dt.timedelta(days=rng.randrange(45), seconds=rng.randrange(86400))
                opt_in = rng.random() > 0.15
                voters.append(
                    Voter(
                        campaign=campaign,
                        registered_by=pick(registrars),
                        name=name,
                        phone=phone,
                        email=f"{name.split()[0].lower()}{len(voters)}@exemplo.com" if rng.random() > 0.6 else "",
                        birth_date=dt.date(1950 + rng.randrange(56), 1 + rng.randrange(12), 1 + rng.randrange(28)),
                        gender=pick(["M", "F", "F", "M", "N"]),
                        cep=f"{cep}{rng.randrange(999):03d}",
                        street=pick(RUAS),
                        number=str(1 + rng.randrange(1500)),
                        neighborhood=hood,
                        city="Campinas",
                        state="SP",
                        latitude=lat + (rng.random() - 0.5) * 0.012,
                        longitude=lng + (rng.random() - 0.5) * 0.012,
                        geo_status=GeoStatus.OK,
                        support_level=pick(APOIO),
                        tags=serialize_tags([pick(TAGS) for _ in range(rng.randrange(3))]) or "",
                        source=pick(["LINK", "QRCODE", "QRCODE", "MANUAL"]),
                        consent_at=created,
                        consent_ip="127.0.0.1",
                        whatsapp_opt_in=opt_in,
                        opt_out_at=created if opt_in and rng.random() > 0.95 else None,
                    )
                )
            created_voters = Voter.objects.bulk_create(voters)
            # auto_now_add ignora o valor informado: ajusta created_at depois (apenas para dados de demonstração)
            for voter, src in zip(created_voters, voters, strict=True):
                Voter.objects.filter(pk=voter.pk).update(created_at=src.consent_at)

            WhatsAppConnection.objects.create(
                campaign=campaign,
                name="Simulador (testes)",
                provider="SANDBOX",
                status="CONNECTED",
                phone_number="+55 19 90000-0000",
                credentials=encrypt_json({"failureRate": "0.05"}),
                webhook_token=random_token(),
                is_default=True,
                rate_per_minute=60,
            )
            MessageTemplate.objects.bulk_create(
                [
                    MessageTemplate(
                        campaign=campaign,
                        created_by=admin,
                        name="Boas-vindas",
                        category="BOAS_VINDAS",
                        body="Olá, {{primeiro_nome}}! 👋 Obrigado por se cadastrar na campanha de {{candidato}} ({{numero}}). "
                        "Vamos juntos fazer mais pelo {{bairro}}! Para não receber mais mensagens, responda SAIR.",
                    ),
                    MessageTemplate(
                        campaign=campaign,
                        created_by=admin,
                        name="Convite para reunião no bairro",
                        category="CONVITE",
                        body="{{primeiro_nome}}, vamos ter um encontro com {{candidato}} no {{bairro}} neste sábado às 10h. "
                        "Sua presença é muito importante! Responda SAIR para não receber mais mensagens.",
                    ),
                ]
            )

        self.stdout.write(self.style.SUCCESS("Campanha demo criada."))
        self.stdout.write(
            f"  admin@demo.efind.com.br | coord1@demo.efind.com.br | cabo1@demo.efind.com.br  — senha: {DEMO_PASSWORD}"
        )
