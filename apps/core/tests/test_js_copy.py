"""Regressão (QA no navegador): o botão ``data-copy`` precisa funcionar também onde ``navigator.clipboard`` não está
disponível ou nega a escrita (HTTP fora de localhost, WebViews de apps, permissão negada). O JS é executado em Node
com fakes mínimos de ``window``/``document``; sem Node instalado o teste é ignorado."""

import json
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APP_JS = Path(settings.BASE_DIR) / "static" / "js" / "app.js"

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function build({ clipboard, execResult }) {
  const calls = { exec: 0, written: null, appended: 0, removed: 0 };
  const listeners = {};
  const textarea = {
    style: {},
    value: "",
    setAttribute() {},
    select() {},
    setSelectionRange() {},
    remove() { calls.removed++; },
  };
  const ctx = {
    console,
    setTimeout,
    clearTimeout,
    Event: class {},
    CustomEvent: class {},
    HTMLInputElement: class {},
    navigator: clipboard === "missing" ? {} : { clipboard: clipboard(calls) },
    document: {
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      querySelectorAll() { return []; },
      createElement() { return textarea; },
      body: { appendChild() { calls.appended++; } },
      execCommand(cmd) {
        calls.exec++;
        calls.copied = textarea.value;
        if (execResult === "throw") throw new Error("denied");
        return execResult;
      },
    },
    dispatchEvent() {},
    addEventListener() {},
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], "utf8"), ctx);
  return { ctx, calls };
}

(async () => {
  const out = {};

  let r = build({ clipboard: (c) => ({ writeText: async (t) => { c.written = t; } }), execResult: true });
  out.api_ok = { ok: await r.ctx.EFind.copyText("abc"), written: r.calls.written, exec: r.calls.exec };

  r = build({ clipboard: () => ({ writeText: async () => { throw new Error("NotAllowedError"); } }), execResult: true });
  out.api_denied = { ok: await r.ctx.EFind.copyText("senha-123"), exec: r.calls.exec, copied: r.calls.copied, removed: r.calls.removed };

  r = build({ clipboard: "missing", execResult: true });
  out.api_missing = { ok: await r.ctx.EFind.copyText("http://x/c/abc/"), exec: r.calls.exec, copied: r.calls.copied };

  r = build({ clipboard: "missing", execResult: false });
  out.all_fail = { ok: await r.ctx.EFind.copyText("x"), removed: r.calls.removed };

  r = build({ clipboard: "missing", execResult: "throw" });
  out.exec_throws = { ok: await r.ctx.EFind.copyText("x"), removed: r.calls.removed };

  process.stdout.write(JSON.stringify(out));
})();
"""


class CopyHelperTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        node = shutil.which("node")
        if not node:
            cls.result = None
            return
        proc = subprocess.run(  # noqa: S603 - comando fixo, sem entrada do usuário
            [node, "-e", HARNESS, str(APP_JS)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        cls.stderr = proc.stderr
        cls.result = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout else None
        cls.returncode = proc.returncode

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("Node não instalado")
        self.assertIsNotNone(self.result, f"harness Node falhou: {getattr(self, 'stderr', '')}")

    def test_uses_clipboard_api_when_available(self):
        self.assertEqual(self.result["api_ok"], {"ok": True, "written": "abc", "exec": 0})

    def test_falls_back_when_clipboard_api_denies_write(self):
        r = self.result["api_denied"]
        self.assertTrue(r["ok"])
        self.assertEqual(r["copied"], "senha-123")
        self.assertEqual(r["exec"], 1)
        self.assertEqual(r["removed"], 1)  # o textarea temporário é sempre removido

    def test_falls_back_when_clipboard_api_is_missing(self):
        # HTTP fora de localhost: navigator.clipboard é undefined e antes lançava TypeError sem toast
        r = self.result["api_missing"]
        self.assertTrue(r["ok"])
        self.assertEqual(r["copied"], "http://x/c/abc/")

    def test_reports_failure_instead_of_throwing(self):
        self.assertEqual(self.result["all_fail"], {"ok": False, "removed": 1})
        self.assertEqual(self.result["exec_throws"], {"ok": False, "removed": 1})
