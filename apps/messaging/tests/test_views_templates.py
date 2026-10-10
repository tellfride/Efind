"""Modelos de mensagem: páginas, criação/edição/duplicação/exclusão, permissões e isolamento entre campanhas."""

from apps.auditlog.models import AuditLog
from apps.core.constants import BroadcastStatus
from apps.messaging.models import MessageTemplate

from .helpers import MessagingTestCase, make_broadcast, make_connection, make_template

LIST = "/painel/mensagens/modelos/"
NEW = "/painel/mensagens/modelos/novo/"


def template_data(**extra):
    data = {
        "name": "Convite para a caminhada",
        "category": "CONVITE",
        "type": "TEXT",
        "media_url": "",
        "body": "Olá, {{primeiro_nome}}! Venha à caminhada de {{candidato}}. Responda SAIR para não receber mais mensagens.",
        "provider_template_name": "",
        "provider_template_language": "pt_BR",
    }
    data.update(extra)
    return data


class TemplatePagesAccessTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.tpl = make_template(self.a, self.admin)

    def test_anonymous_is_redirected_to_login(self):
        for url in (LIST, NEW, f"{LIST}{self.tpl.pk}/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/login/"), url)

    def test_admin_sees_all_pages(self):
        self.login(self.admin)
        for url in (LIST, NEW, f"{LIST}{self.tpl.pk}/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_coordinator_has_read_only_access_by_default(self):
        self.login(self.coord1)
        self.assertEqual(self.client.get(LIST).status_code, 200)
        self.assertEqual(self.client.get(NEW).status_code, 403)
        response = self.client.get(f"{LIST}{self.tpl.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["read_only"])
        self.assertNotContains(response, "Salvar modelo")
        # não consegue salvar nem por POST direto
        response = self.client.post(f"{LIST}{self.tpl.pk}/", template_data(name="Alterado"))
        self.assertEqual(response.status_code, 403)
        self.tpl.refresh_from_db()
        self.assertNotEqual(self.tpl.name, "Alterado")
        self.assertEqual(self.client.post(NEW, template_data()).status_code, 403)
        self.assertEqual(self.client.post(f"{LIST}{self.tpl.pk}/duplicar/").status_code, 403)
        self.assertEqual(self.client.post(f"{LIST}{self.tpl.pk}/excluir/").status_code, 403)
        self.assertEqual(MessageTemplate.objects.count(), 1)

    def test_cabo_has_no_access(self):
        self.login(self.cabo1)
        for url in (LIST, NEW, f"{LIST}{self.tpl.pk}/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_super_admin_is_sent_to_super_area(self):
        self.login(self.superuser)
        response = self.client.get(LIST)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/super/")

    def test_granted_permission_takes_effect_immediately(self):
        self.grant(self.cabo1, "modelos", view=True, create=True)
        self.login(self.cabo1)
        self.assertEqual(self.client.get(LIST).status_code, 200)
        self.assertEqual(self.client.post(NEW, template_data()).status_code, 302)

    def test_mutations_only_via_post(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(f"{LIST}{self.tpl.pk}/duplicar/").status_code, 405)
        self.assertEqual(self.client.get(f"{LIST}{self.tpl.pk}/excluir/").status_code, 405)


class TemplateListTests(MessagingTestCase):
    def test_empty_state_for_new_campaign(self):
        self.login(self.admin)
        response = self.client.get(LIST)
        self.assertContains(response, "Nenhum modelo criado ainda")

    def test_cards_show_badges_and_filters_work(self):
        make_template(self.a, self.admin, name="Convite sábado", category="CONVITE", body="Venha *sábado*", provider_template_name="convite_ok")
        make_template(self.a, self.admin, name="Obrigado", category="AGRADECIMENTO", body="Muito obrigado")
        self.login(self.admin)
        response = self.client.get(LIST)
        self.assertContains(response, "Convite sábado")
        self.assertContains(response, "Template aprovado: convite_ok")
        self.assertEqual(len(response.context["templates"]), 2)
        only = self.client.get(LIST, {"categoria": "AGRADECIMENTO"})
        self.assertEqual([t.name for t in only.context["templates"]], ["Obrigado"])
        found = self.client.get(LIST, {"q": "sábado"})
        self.assertEqual([t.name for t in found.context["templates"]], ["Convite sábado"])
        nothing = self.client.get(LIST, {"q": "inexistente"})
        self.assertContains(nothing, "Nenhum modelo encontrado")
        # categoria inválida é ignorada
        self.assertEqual(len(self.client.get(LIST, {"categoria": "XPTO"}).context["templates"]), 2)

    def test_other_campaign_templates_are_never_listed(self):
        make_template(self.b, self.admin_b, name="Segredo da outra campanha")
        make_template(self.a, self.admin, name="Meu modelo")
        self.login(self.admin)
        response = self.client.get(LIST)
        self.assertContains(response, "Meu modelo")
        self.assertNotContains(response, "Segredo da outra campanha")

    def test_template_name_is_escaped(self):
        make_template(self.a, self.admin, name="<script>alert(1)</script>")
        self.login(self.admin)
        response = self.client.get(LIST)
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_locked_template_cannot_be_deleted_from_the_card(self):
        tpl = make_template(self.a, self.admin, name="Em uso")
        make_broadcast(self.a, self.admin, tpl, make_connection(self.a), status=BroadcastStatus.PAUSED)
        self.login(self.admin)
        response = self.client.get(LIST)
        self.assertTrue(response.context["templates"][0].is_locked)
        self.assertContains(response, "Não é possível excluir: modelo em uso")

    def test_use_in_broadcast_link_requires_create_permission(self):
        tpl = make_template(self.a, self.admin)
        self.login(self.coord1)
        self.assertNotContains(self.client.get(LIST), f"/painel/mensagens/disparos/novo/?modelo={tpl.pk}")
        self.grant(self.coord1, "disparos", create=True)
        self.assertContains(self.client.get(LIST), f"/painel/mensagens/disparos/novo/?modelo={tpl.pk}")


class TemplateCreateEditTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def test_editor_page_has_variables_preview_and_official_section(self):
        response = self.client.get(NEW)
        self.assertContains(response, "API oficial (Meta / 360dialog / Twilio)")
        self.assertContains(response, "Pré-visualização")
        self.assertContains(response, "Adicionar instrução de descadastro")
        config = response.context["editor_config"]
        self.assertIn("primeiro_nome", [v["key"] for v in config["variables"]])
        self.assertEqual(config["bodyMax"], 4096)
        self.assertEqual(config["example"]["primeiro_nome"], "Maria")

    def test_create_valid_template(self):
        response = self.client.post(
            NEW,
            template_data(provider_template_name="convite_evento", provider_variables=["primeiro_nome", "bairro", "primeiro_nome"]),
        )
        self.assertRedirects(response, LIST, fetch_redirect_response=False)
        tpl = MessageTemplate.objects.get()
        self.assertEqual(tpl.campaign_id, self.a.pk)
        self.assertEqual(tpl.created_by_id, self.admin.pk)
        self.assertEqual(tpl.category, "CONVITE")
        self.assertEqual(tpl.provider_template_name, "convite_evento")
        self.assertEqual(tpl.provider_variables, ["primeiro_nome", "bairro", "primeiro_nome"])  # ordem preservada
        row = AuditLog.objects.get(action="template.create")
        self.assertEqual((row.entity_id, row.campaign_id, row.user_id), (str(tpl.pk), self.a.pk, self.admin.pk))
        self.assertNotIn("Olá", str(row.details))

    def test_body_line_breaks_are_normalized(self):
        self.client.post(NEW, template_data(body="Linha 1\r\nLinha 2 Responda SAIR"))
        self.assertEqual(MessageTemplate.objects.get().body, "Linha 1\nLinha 2 Responda SAIR")

    def test_validation_errors_rerender_the_form(self):
        cases = {
            "name": template_data(name="ab"),
            "body": template_data(body="   "),
            "category": template_data(category="OUTRA"),
            "type": template_data(type="AUDIO"),
            "media_url": template_data(type="IMAGE", media_url=""),
            "provider_template_name": template_data(provider_template_name="Nome Inválido!"),
            "provider_template_language": template_data(provider_template_language="português"),
            "provider_variables": template_data(provider_variables=["nao_existe"]),
        }
        for field, data in cases.items():
            response = self.client.post(NEW, data)
            self.assertEqual(response.status_code, 200, field)
            self.assertIn(field, response.context["form"].errors, field)
        self.assertEqual(MessageTemplate.objects.count(), 0)

    def test_body_over_limit_is_rejected(self):
        response = self.client.post(NEW, template_data(body="a" * 4097))
        self.assertIn("body", response.context["form"].errors)

    def test_media_requires_https(self):
        for url in ("http://exemplo.com.br/foto.jpg", "ftp://exemplo.com.br/foto.jpg", "javascript:alert(1)"):
            response = self.client.post(NEW, template_data(type="IMAGE", media_url=url))
            self.assertIn("media_url", response.context["form"].errors, url)
        ok = self.client.post(NEW, template_data(type="IMAGE", media_url="https://exemplo.com.br/foto.jpg"))
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(MessageTemplate.objects.get().media_url, "https://exemplo.com.br/foto.jpg")

    def test_text_template_drops_media_url(self):
        self.client.post(NEW, template_data(type="TEXT", media_url="https://exemplo.com.br/foto.jpg"))
        self.assertEqual(MessageTemplate.objects.get().media_url, "")

    def test_edit_updates_and_audits(self):
        tpl = make_template(self.a, self.admin, name="Antigo")
        response = self.client.post(f"{LIST}{tpl.pk}/", template_data(name="Novo nome", provider_variables=["bairro"]))
        self.assertEqual(response.status_code, 302)
        tpl.refresh_from_db()
        self.assertEqual((tpl.name, tpl.provider_variables), ("Novo nome", ["bairro"]))
        self.assertTrue(AuditLog.objects.filter(action="template.update", entity_id=str(tpl.pk)).exists())

    def test_edit_form_is_prefilled(self):
        tpl = make_template(self.a, self.admin, name="Convite", provider_variables=["cidade", "bairro"])
        response = self.client.get(f"{LIST}{tpl.pk}/")
        self.assertContains(response, 'value="Convite"')
        self.assertEqual(response.context["editor_config"]["initial"]["rows"], ["cidade", "bairro"])

    def test_other_campaign_template_is_404(self):
        foreign = make_template(self.b, self.admin_b, name="Alheio")
        self.assertEqual(self.client.get(f"{LIST}{foreign.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"{LIST}{foreign.pk}/", template_data(name="Invadido")).status_code, 404)
        self.assertEqual(self.client.post(f"{LIST}{foreign.pk}/duplicar/").status_code, 404)
        self.assertEqual(self.client.post(f"{LIST}{foreign.pk}/excluir/").status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, "Alheio")
        self.assertEqual(MessageTemplate.objects.filter(campaign=self.b).count(), 1)

    def test_csrf_is_enforced(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(NEW, template_data()).status_code, 403)
        self.assertEqual(MessageTemplate.objects.count(), 0)


class TemplateDuplicateDeleteTests(MessagingTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)
        self.tpl = make_template(self.a, self.admin, name="Original", provider_template_name="abc", provider_variables=["bairro"])

    def test_duplicate_copies_everything_but_the_name(self):
        response = self.client.post(f"{LIST}{self.tpl.pk}/duplicar/")
        copy = MessageTemplate.objects.exclude(pk=self.tpl.pk).get()
        self.assertRedirects(response, f"{LIST}{copy.pk}/", fetch_redirect_response=False)
        self.assertEqual(copy.name, "Original (cópia)")
        self.assertEqual((copy.body, copy.provider_template_name, copy.provider_variables), (self.tpl.body, "abc", ["bairro"]))
        self.assertEqual((copy.campaign_id, copy.created_by_id), (self.a.pk, self.admin.pk))
        self.assertTrue(AuditLog.objects.filter(action="template.create", entity_id=str(copy.pk)).exists())

    def test_duplicate_name_fits_the_limit(self):
        long = make_template(self.a, self.admin, name="x" * 120)
        self.client.post(f"{LIST}{long.pk}/duplicar/")
        self.assertTrue(MessageTemplate.objects.filter(name__endswith="(cópia)").exists())
        self.assertLessEqual(max(len(n) for n in MessageTemplate.objects.values_list("name", flat=True)), 120)

    def test_delete_unused_template(self):
        response = self.client.post(f"{LIST}{self.tpl.pk}/excluir/")
        self.assertRedirects(response, LIST, fetch_redirect_response=False)
        self.assertFalse(MessageTemplate.objects.filter(pk=self.tpl.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="template.delete", entity_id=str(self.tpl.pk)).exists())

    def test_delete_blocked_while_used_by_active_broadcast(self):
        conn = make_connection(self.a)
        for status in (BroadcastStatus.SCHEDULED, BroadcastStatus.RUNNING, BroadcastStatus.PAUSED):
            broadcast = make_broadcast(self.a, self.admin, self.tpl, conn, status=status)
            response = self.client.post(f"{LIST}{self.tpl.pk}/excluir/", follow=True)
            self.assertTrue(MessageTemplate.objects.filter(pk=self.tpl.pk).exists(), status)
            self.assertIn("em uso", " ".join(str(m) for m in response.context["messages"]))
            broadcast.delete()

    def test_delete_allowed_when_only_finished_broadcasts_use_it(self):
        conn = make_connection(self.a)
        finished = make_broadcast(self.a, self.admin, self.tpl, conn, status=BroadcastStatus.COMPLETED)
        self.client.post(f"{LIST}{self.tpl.pk}/excluir/")
        self.assertFalse(MessageTemplate.objects.filter(pk=self.tpl.pk).exists())
        finished.refresh_from_db()
        self.assertIsNone(finished.template_id)  # histórico preservado, sem o modelo
