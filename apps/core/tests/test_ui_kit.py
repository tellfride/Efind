"""Garante que os componentes do kit de UI renderizam (os módulos dependem deles)."""

from django.core.paginator import Paginator
from django.template import Context, Template
from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.campaigns.bootstrap import bootstrap_campaign
from apps.campaigns.models import Campaign
from apps.core.filter_options import build_filter_panel, get_voter_filter_options
from apps.core.forms import PhoneField, StyledFormMixin
from apps.core.voter_filters import parse_voter_filters
from apps.voters.models import Voter

from django import forms


class DemoForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Nome", help_text="Seu nome completo")
    phone = PhoneField(label="Telefone")
    agree = forms.BooleanField(label="Concordo")
    kind = forms.ChoiceField(choices=[("a", "A"), ("b", "B")])


def render(source, **ctx):
    return Template(source).render(Context(ctx))


class UiKitTests(TestCase):
    def test_icon_badge_progress_avatar(self):
        html = render('{% icon "users" "size-5" %}{% badge "Ativo" "green" %}{% progress 30 100 "green" %}{% avatar "Maria Silva" %}')
        self.assertIn("<svg", html)
        self.assertIn("badge-green", html)
        self.assertIn('aria-valuenow="30"', html)
        self.assertIn(">MS<", html)

    def test_unknown_icon_falls_back_and_path_traversal_is_blocked(self):
        self.assertIn("<circle", render('{% icon "nao-existe" %}'))
        self.assertIn("<circle", render('{% icon "../../.env" %}'))

    def test_block_tags(self):
        html = render(
            '{% page_header title="Apoiadores" description="Lista" %}<a>Novo</a>{% endpage_header %}'
            '{% card title="Resumo" %}conteúdo{% endcard %}'
            '{% empty_state icon="inbox" title="Vazio" %}<b>ação</b>{% endempty_state %}'
            '{% alert "warning" title="Atenção" %}texto{% endalert %}'
        )
        for expected in ("Apoiadores", "<a>Novo</a>", "Resumo", "conteúdo", "Vazio", "<b>ação</b>", "alert-warning"):
            self.assertIn(expected, html)

    def test_escapes_user_content(self):
        html = render('{% badge text "red" %}{% stat_card "L" value %}', text="<script>x</script>", value="<b>1</b>")
        self.assertNotIn("<script>x", html)
        self.assertNotIn("<b>1</b>", html)

    def test_stat_card_and_filters(self):
        html = render('{% stat_card "Apoiadores" total icon="users-round" tone="green" hint="na rede" %}{{ 1234567|num }}|{{ 12.34|pct }}|{{ "5511987654321"|phone }}|{{ "13010001"|cep }}', total=42)
        self.assertIn("42", html)
        self.assertIn("1.234.567|12,3%|(11) 98765-4321|13010-001", html)

    def test_form_field_tag(self):
        form = DemoForm({"name": "", "phone": "123"})
        html = render("{% field form.name %}{% field form.phone %}{% field form.agree %}{% field form.kind %}", form=form)
        self.assertIn('class="input"', html)
        self.assertIn('class="select"', html)
        self.assertIn('class="checkbox"', html)
        self.assertIn("Informe um telefone válido", html)
        self.assertIn('aria-invalid="true"', html)

    def test_pagination_keeps_querystring(self):
        request = RequestFactory().get("/painel/apoiadores/", {"q": "ana", "page": "2"})
        page = Paginator(list(range(100)), 25).page(2)
        html = render("{% pagination page %}", request=request, page=page)
        self.assertIn("q=ana", html)
        self.assertIn("page=3", html)
        self.assertIn("26–50 de 100", html)

    def test_qs_tag_removes_empty_values(self):
        request = RequestFactory().get("/x/", {"q": "ana", "page": "2"})
        self.assertEqual(render("{% qs page=None %}", request=request), "?q=ana")


class VoterFiltersComponentTests(TestCase):
    def test_renders_with_real_options(self):
        campaign = Campaign.objects.create(slug="c", candidate_name="C", ballot_name="C", office="VEREADOR", election_year=2026)
        bootstrap_campaign(campaign)
        admin = User.objects.create_user("a@c.com", "Senha@12345", name="Admin", role="ADMIN", campaign=campaign)
        Voter.objects.create(campaign=campaign, registered_by=admin, name="A", phone="5511900000001", neighborhood="Centro", city="Campinas", tags=",saude,")
        options = get_voter_filter_options(admin)
        self.assertEqual([o["value"] for o in options["neighborhoods"]], ["Centro"])
        self.assertEqual([o["value"] for o in options["tags"]], ["saude"])

        request = RequestFactory().get("/painel/apoiadores/", {"bairro": "Centro", "idade_min": "18"})
        filters = parse_voter_filters(request.GET)
        html = render("{% voter_filters filters options %}", request=request, filters=filters, options=options)
        self.assertIn('name="q"', html)
        self.assertIn("multiSelect(", html)
        self.assertIn("&quot;Centro&quot;", html)  # opção/seleção embutida de forma segura no atributo
        self.assertIn('value="18"', html)
        self.assertIn("2 filtros ativos", html)
        self.assertIn('action="/painel/apoiadores/"', html)

    def test_panel_opens_when_a_secondary_filter_is_active(self):
        # Regressão (QA no navegador): com idade/datas/mapa/WhatsApp ativos o painel abria recolhido, e o usuário via
        # uma lista "misteriosamente" menor, sem os campos que causavam isso à vista.
        options = {"neighborhoods": [], "cities": [], "coordinators": [], "members": [], "tags": [], "electoral_zones": []}

        def expanded(params):
            return build_filter_panel(parse_voter_filters(RequestFactory().get("/x/", params).GET), options)["expanded"]

        self.assertFalse(expanded({}))
        self.assertFalse(expanded({"q": "ana"}))  # busca é filtro primário: sempre à vista
        for params in (
            {"idade_min": "18"},
            {"idade_max": "40"},
            {"de": "2026-01-01"},
            {"ate": "2026-12-31"},
            {"geo": "1"},
            {"geo": "0"},
            {"whatsapp": "1"},
            {"genero": "F"},
            {"apoio": "APOIADOR"},
        ):
            with self.subTest(params=params):
                self.assertTrue(expanded(params))
        # valor inválido é descartado pelo parser e não deve abrir o painel
        self.assertFalse(expanded({"idade_min": "abc"}))

    def test_hides_filters_without_options(self):
        html = render(
            "{% voter_filters filters options %}",
            request=RequestFactory().get("/x/"),
            filters={},
            options={"neighborhoods": [], "cities": [], "coordinators": [], "members": [], "tags": [], "electoral_zones": []},
        )
        self.assertNotIn("Coordenadores", html)
        self.assertNotIn("Tags", html)
