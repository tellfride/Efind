from django.db import migrations

# Descrição do dashboard-modelo "Territorial" gravada nas campanhas existentes (as novas já nascem com o texto novo).
OLD = "Onde estão os eleitores: bairros, cidades e perfil da base."
NEW = "Onde estão os apoiadores: bairros, cidades e perfil da base."


def rename(apps, schema_editor):
    """Só troca descrições idênticas ao texto padrão antigo: o que a equipe editou à mão não é tocado."""
    Dashboard = apps.get_model("dashboards", "Dashboard")
    Dashboard.objects.filter(description=OLD).update(description=NEW)


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(rename, migrations.RunPython.noop),
    ]
