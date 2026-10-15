"""Terminologia: a interface, os textos e a documentação dizem "apoiador(es)", nunca "eleitor(es)".

"Eleitoral" (cabo eleitoral, zona eleitoral, campanha eleitoral) continua valendo. Ficam de fora, por serem
identificadores internos: o módulo de permissão "eleitores" (gravado no banco) e os apelidos de colunas de planilhas antigas.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
WORD = re.compile(r"(?<!\w)[Ee]leitor(?:es|as|a)?(?!\w)")
INTERNAL_KEY = re.compile(r"""(["'`])eleitor(?:es)?\1|\bperms\.eleitores\b""")
ALLOWED_FILES = {"apps/voters/urls.py"}  # redireciona os endereços antigos (/painel/eleitores/...)
SCAN = [
    ("templates", "*.html"),
    ("static/js", "*.js"),
    ("apps", "*.py"),
    ("docs", "*.md"),
    (".", "README.md"),
]
SKIP_PARTS = ("/tests/", "/migrations/", "static/vendor/")


def source_files():
    for folder, pattern in SCAN:
        base = ROOT / folder
        files = base.rglob(pattern) if folder != "." else base.glob(pattern)
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            if not any(part in f"/{rel}" for part in SKIP_PARTS) and rel not in ALLOWED_FILES:
                yield rel, path


class TerminologyTests(SimpleTestCase):
    def test_no_voter_wording_in_interface_texts_or_docs(self):
        found = []
        for rel, path in source_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if WORD.search(INTERNAL_KEY.sub("", line)):
                    found.append(f"{rel}:{number}: {line.strip()[:110]}")
        self.assertEqual(found, [], "use 'apoiador(es)' em vez de 'eleitor(es)':\n" + "\n".join(found))
