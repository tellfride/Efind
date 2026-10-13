"""Diálogo de confirmação próprio (substitui window.confirm, suprimido em WebViews como o do WhatsApp).
O JS roda em Node com um DOM falso mínimo; sem Node instalado o teste é ignorado."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APP_JS = Path(settings.BASE_DIR) / "static" / "js" / "app.js"

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const listeners = {};
function addDocListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); }
function removeDocListener(type, fn) { listeners[type] = (listeners[type] || []).filter((f) => f !== fn); }
function dispatch(type, event) {
  event.type = type;
  event.prevented = false;
  event.stopped = false;
  event.preventDefault = () => { event.prevented = true; };
  event.stopImmediatePropagation = () => { event.stopped = true; };
  for (const fn of [...(listeners[type] || [])]) { if (event.stopped) break; fn(event); }
  return event;
}

const doc = { activeElement: null, body: null };
function makeEl(tag) {
  const el = {
    tagName: tag.toUpperCase(), children: [], attrs: {}, className: "", textContent: "", id: "", dataset: {}, listeners: {},
    removed: false,
    classList: { contains: (c) => el.className.split(/\s+/).includes(c) },
    setAttribute(k, v) { el.attrs[k] = v; },
    addEventListener(t, fn) { (el.listeners[t] = el.listeners[t] || []).push(fn); },
    append(...c) { el.children.push(...c); },
    remove() { el.removed = true; if (doc.body) doc.body.children = doc.body.children.filter((c) => c !== el); },
    focus() { doc.activeElement = el; },
    closest(sel) {
      if (sel === "[data-confirm]") return el.dataset.confirm !== undefined ? el : null;
      if (sel === "[data-copy]") return el.dataset.copy !== undefined ? el : null;
      return null;
    },
    fire(t, ev) { (el.listeners[t] || []).forEach((fn) => fn(ev || { target: el })); },
  };
  return el;
}
doc.body = makeEl("body");
doc.createElement = makeEl;
doc.addEventListener = addDocListener;
doc.removeEventListener = removeDocListener;
doc.querySelectorAll = () => [];

const ctx = { console, setTimeout, clearTimeout, Event: class {}, CustomEvent: class {}, HTMLInputElement: class {},
  navigator: {}, document: doc, dispatchEvent() {}, addEventListener() {} };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[process.argv.length - 1], "utf8"), ctx);

const tick = () => new Promise((r) => setTimeout(r, 0));
const dialog = () => doc.body.children.find((c) => c.attrs && "data-confirm-dialog" in c.attrs);
const parts = (ov) => {
  const box = ov.children[0];
  const [title, text, actions] = box.children;
  return { box, title, text, cancel: actions.children[0], ok: actions.children[1] };
};

function makeForm({ confirmOnForm, confirmOnButton, danger }) {
  const calls = { requestSubmit: [], submitEvents: [] };
  const form = makeEl("form");
  const button = makeEl("button");
  button.type = "submit";
  button.form = form;
  button.textContent = " Suspender ";
  if (danger) button.className = "btn btn-danger";
  else button.className = "btn btn-primary";
  if (confirmOnForm) form.dataset.confirm = confirmOnForm;
  if (confirmOnButton) button.dataset.confirm = confirmOnButton;
  form.querySelector = (sel) => (sel === "[type=submit]" ? button : null);
  form.requestSubmit = (submitter) => {
    calls.requestSubmit.push(submitter);
    calls.submitEvents.push(dispatch("submit", { target: form, submitter }));
  };
  return { form, button, calls };
}

(async () => {
  const out = {};

  // 1) botão de submit com data-confirm: pergunta, e só envia depois de confirmar (uma única vez)
  let f = makeForm({ confirmOnButton: "Suspender a campanha?", danger: true });
  let ev = dispatch("submit", { target: f.form, submitter: f.button });
  let ov = dialog();
  let p = ov && parts(ov);
  out.submit_blocked = { prevented: ev.prevented, stopped: ev.stopped, hasDialog: !!ov, text: p && p.text.textContent,
    title: p && p.title.textContent, okLabel: p && p.ok.textContent, okClass: p && p.ok.className,
    role: p && p.box.attrs.role, modal: p && p.box.attrs["aria-modal"], focusOnCancel: doc.activeElement === (p && p.cancel) };
  p.ok.fire("click");
  await tick();
  out.after_confirm = { requestSubmit: f.calls.requestSubmit.length, sameSubmitter: f.calls.requestSubmit[0] === f.button,
    secondPassPrevented: f.calls.submitEvents[0] && f.calls.submitEvents[0].prevented, dialogGone: !dialog() };

  // 2) cancelar: nada é enviado e a próxima tentativa pergunta de novo
  f = makeForm({ confirmOnButton: "Excluir?", danger: true });
  dispatch("submit", { target: f.form, submitter: f.button });
  parts(dialog()).cancel.fire("click");
  await tick();
  out.cancel = { requestSubmit: f.calls.requestSubmit.length, dialogGone: !dialog() };
  ev = dispatch("submit", { target: f.form, submitter: f.button });
  out.cancel_asks_again = { prevented: ev.prevented, hasDialog: !!dialog() };
  parts(dialog()).cancel.fire("click");
  await tick();

  // 3) Esc cancela
  f = makeForm({ confirmOnButton: "Excluir?" });
  dispatch("submit", { target: f.form, submitter: f.button });
  dispatch("keydown", { key: "Escape" });
  await tick();
  out.escape = { requestSubmit: f.calls.requestSubmit.length, dialogGone: !dialog(), focusRestored: true };

  // 4) clique no fundo cancela; clique dentro da caixa não
  f = makeForm({ confirmOnButton: "Excluir?" });
  dispatch("submit", { target: f.form, submitter: f.button });
  ov = dialog();
  const box = parts(ov).box;
  ov.fire("click", { target: box });
  out.click_inside_keeps_open = !!dialog();
  ov.fire("click", { target: ov });
  await tick();
  out.backdrop = { dialogGone: !dialog(), requestSubmit: f.calls.requestSubmit.length };

  // 5) Tab alterna entre os dois botões (foco preso)
  f = makeForm({ confirmOnButton: "Excluir?" });
  dispatch("submit", { target: f.form, submitter: f.button });
  p = parts(dialog());
  const tabs = [];
  for (let i = 0; i < 3; i++) {
    const e = dispatch("keydown", { key: "Tab" });
    tabs.push([e.prevented, doc.activeElement === p.ok ? "ok" : doc.activeElement === p.cancel ? "cancel" : "?"]);
  }
  out.tab_trap = tabs;
  p.cancel.fire("click");
  await tick();

  // 6) data-confirm no <form> (sem submitter com confirmação) e botão primário (azul)
  f = makeForm({ confirmOnForm: "Restaurar o padrão?", danger: false });
  ev = dispatch("submit", { target: f.form, submitter: f.button });
  p = parts(dialog());
  out.form_level = { prevented: ev.prevented, text: p.text.textContent, okClass: p.ok.className };
  p.ok.fire("click");
  await tick();
  out.form_level_sent = f.calls.requestSubmit.length;

  // 7) elemento sem data-confirm passa direto
  f = makeForm({});
  ev = dispatch("submit", { target: f.form, submitter: f.button });
  out.no_confirm = { prevented: ev.prevented, hasDialog: !!dialog() };

  // 8) botão/link comum (não submit) com data-confirm: confirmar repete o clique, que não pergunta de novo
  const link = makeEl("a");
  link.dataset.confirm = "Sair desta página?";
  link.textContent = "Excluir";
  link.className = "btn btn-danger";
  let clicks = 0, replayPrevented = null;
  link.click = () => { clicks++; replayPrevented = dispatch("click", { target: link }).prevented; };
  ev = dispatch("click", { target: link });
  out.link = { prevented: ev.prevented, hasDialog: !!dialog() };
  parts(dialog()).ok.fire("click");
  await tick();
  out.link_after = { clicks, replayPrevented, dialogGone: !dialog() };

  // 9) a mensagem vai como texto (sem interpretar HTML)
  f = makeForm({ confirmOnButton: "<img src=x onerror=alert(1)>" });
  dispatch("submit", { target: f.form, submitter: f.button });
  p = parts(dialog());
  out.text_only = { text: p.text.textContent, hasInnerHTML: "innerHTML" in p.text };
  p.cancel.fire("click");
  await tick();

  out.api = typeof ctx.EFind.confirm;
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


class ConfirmDialogJsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node não instalado")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "harness.js"
            script.write_text(HARNESS, encoding="utf-8")
            result = subprocess.run([node, str(script), str(APP_JS)], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise AssertionError(f"harness falhou: {result.stderr[-800:]}")
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_submit_is_blocked_until_confirmed(self):
        out = self.out["submit_blocked"]
        self.assertTrue(out["prevented"] and out["stopped"] and out["hasDialog"])
        self.assertEqual(out["text"], "Suspender a campanha?")
        self.assertEqual(out["okLabel"], "Suspender")  # rótulo = texto do botão que disparou
        self.assertIn("btn-danger", out["okClass"])
        self.assertEqual((out["role"], out["modal"]), ("alertdialog", "true"))
        self.assertTrue(out["focusOnCancel"])  # ação destrutiva: foco inicial em "Cancelar"
        after = self.out["after_confirm"]
        self.assertEqual(after["requestSubmit"], 1)
        self.assertTrue(after["sameSubmitter"])
        self.assertFalse(after["secondPassPrevented"])  # o reenvio já confirmado não pergunta de novo
        self.assertTrue(after["dialogGone"])

    def test_cancel_escape_and_backdrop_do_not_submit(self):
        self.assertEqual(self.out["cancel"], {"requestSubmit": 0, "dialogGone": True})
        self.assertTrue(self.out["cancel_asks_again"]["prevented"])
        self.assertTrue(self.out["cancel_asks_again"]["hasDialog"])
        self.assertEqual(self.out["escape"]["requestSubmit"], 0)
        self.assertTrue(self.out["escape"]["dialogGone"])
        self.assertTrue(self.out["click_inside_keeps_open"])
        self.assertEqual(self.out["backdrop"], {"dialogGone": True, "requestSubmit": 0})

    def test_focus_stays_inside_the_dialog(self):
        self.assertEqual(self.out["tab_trap"], [[True, "ok"], [True, "cancel"], [True, "ok"]])

    def test_form_level_confirm_and_primary_tone(self):
        out = self.out["form_level"]
        self.assertTrue(out["prevented"])
        self.assertEqual(out["text"], "Restaurar o padrão?")
        self.assertIn("btn-primary", out["okClass"])
        self.assertNotIn("btn-danger", out["okClass"])
        self.assertEqual(self.out["form_level_sent"], 1)

    def test_elements_without_data_confirm_are_untouched(self):
        self.assertEqual(self.out["no_confirm"], {"prevented": False, "hasDialog": False})

    def test_plain_links_replay_the_click_after_confirming(self):
        self.assertEqual(self.out["link"], {"prevented": True, "hasDialog": True})
        self.assertEqual(self.out["link_after"], {"clicks": 1, "replayPrevented": False, "dialogGone": True})

    def test_message_is_rendered_as_text_not_html(self):
        self.assertEqual(self.out["text_only"]["text"], "<img src=x onerror=alert(1)>")
        self.assertEqual(self.out["api"], "function")
