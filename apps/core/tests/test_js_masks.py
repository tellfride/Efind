"""Regressão (QA no navegador): a máscara de telefone do front (`EFind.maskPhone`, static/js/app.js) precisa ler
números colados com DDI/zero como o servidor (`normalize_br_phone`). Executa o JS em Node (ignorado sem Node)."""

import json
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.phone import normalize_br_phone

APP_JS = Path(settings.BASE_DIR) / "static" / "js" / "app.js"

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const ctx = {
  console, setTimeout, clearTimeout,
  Event: class {}, CustomEvent: class {}, HTMLInputElement: class {},
  navigator: {},
  document: { addEventListener() {}, querySelectorAll() { return []; } },
  dispatchEvent() {}, addEventListener() {},
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], "utf8"), ctx);
const inputs = JSON.parse(process.env.MASK_INPUTS);
process.stdout.write(JSON.stringify(inputs.map((v) => ctx.EFind.maskPhone(v))));
"""

CASES = [
    # (texto digitado/colado, máscara esperada)
    ("19988776655", "(19) 98877-6655"),
    ("(19) 98877-6655", "(19) 98877-6655"),
    ("1933334444", "(19) 3333-4444"),
    ("+55 19 98877-6655", "(19) 98877-6655"),
    ("+5519988776655", "(19) 98877-6655"),
    ("5519988776655", "(19) 98877-6655"),  # DDI sem "+": 13 dígitos
    ("551933334444", "(19) 3333-4444"),  # DDI + fixo: 12 dígitos
    ("0055 19 98877-6655", "(19) 98877-6655"),
    ("019988776655", "(19) 98877-6655"),  # 0 + DDD + celular
    # DDDs 91–99 corrompiam em silêncio: "(55) 91988-7766" é um telefone válido, só que de outra pessoa
    ("+55 91 98877-6655", "(91) 98877-6655"),
    ("5591988776655", "(91) 98877-6655"),
    # DDD 55 (RS) continua intacto, com ou sem DDI
    ("(55) 99999-8888", "(55) 99999-8888"),
    ("55999998888", "(55) 99999-8888"),
    ("+55 55 99999-8888", "(55) 99999-8888"),
    ("5555999998888", "(55) 99999-8888"),
    # digitação progressiva continua formatando
    ("", ""),
    ("1", "(1"),
    ("19", "(19"),
    ("199", "(19) 9"),
]


class PhoneMaskTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        node = shutil.which("node")
        cls.result = None
        cls.stderr = ""
        if not node:
            return
        import os

        proc = subprocess.run(  # noqa: S603 - comando fixo, sem entrada do usuário
            [node, "-e", HARNESS, str(APP_JS)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={**os.environ, "MASK_INPUTS": json.dumps([c[0] for c in CASES])},
        )
        cls.stderr = proc.stderr
        cls.result = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout else None

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("Node não instalado")
        self.assertIsNotNone(self.result, f"harness Node falhou: {self.stderr}")

    def test_mask_matches_expected_formatting(self):
        for (raw, expected), got in zip(CASES, self.result):
            with self.subTest(raw=raw):
                self.assertEqual(got, expected)

    def test_masked_value_normalizes_to_the_same_phone_as_the_raw_text(self):
        # o que o usuário vê no campo precisa ser o telefone que o servidor entenderia do texto original
        for raw, _ in CASES:
            expected = normalize_br_phone(raw)
            if not expected:
                continue
            masked = self.result[[c[0] for c in CASES].index(raw)]
            with self.subTest(raw=raw):
                self.assertEqual(normalize_br_phone(masked), expected)
