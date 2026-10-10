/* Editor de modelos de mensagem (Alpine): variáveis, formatação, avisos, parâmetros do template oficial e
 * pré-visualização ao vivo. Depende de whatsapp-format.js (window.EFindWA). */
document.addEventListener("alpine:init", () => {
  window.Alpine.data("templateEditor", (config) => ({
    variables: config.variables || [],
    example: config.example || {},
    keywords: config.optOutKeywords || [],
    optOutInstruction: config.optOutInstruction || "",
    bodyMax: config.bodyMax || 4096,
    readOnly: !!config.readOnly,
    mediaLabels: config.mediaLabels || {},
    body: (config.initial && config.initial.body) || "",
    kind: (config.initial && config.initial.kind) || "TEXT",
    mediaUrl: (config.initial && config.initial.mediaUrl) || "",
    rows: [...((config.initial && config.initial.rows) || [])],

    init() {
      const render = () => this.renderPreview();
      this.$watch("body", render);
      this.$watch("kind", render);
      this.$watch("mediaUrl", render);
      this.$nextTick(render);
    },

    // ---------------------------------------------------------- derivados
    get length() {
      return window.EFindWA.codePointLength(this.body);
    },
    get overLimit() {
      return this.length > this.bodyMax;
    },
    get nearLimit() {
      return this.length > this.bodyMax * 0.9;
    },
    get unknown() {
      return window.EFindWA.unknownVariables(
        this.body,
        this.variables.map((v) => v.key),
      );
    },
    get unknownText() {
      return this.unknown.map((k) => "{{" + k + "}}").join(", ");
    },
    get missingOptOut() {
      return this.body.trim() !== "" && !window.EFindWA.hasOptOut(this.body, this.keywords);
    },
    get mediaLabel() {
      return this.kind !== "TEXT" ? this.mediaLabels[this.kind] || "Mídia" : "";
    },
    token(key) {
      return "{{" + key + "}}";
    },
    placeholder(i) {
      return "{{" + (i + 1) + "}}";
    },

    // ---------------------------------------------------------- edição do texto
    _apply(result, start, end) {
      const ta = this.$refs.body;
      this.body = result.text;
      this.$nextTick(() => {
        ta.focus();
        ta.setSelectionRange(start, end);
      });
    },
    insertVariable(key) {
      if (this.readOnly) return;
      const ta = this.$refs.body;
      const r = window.EFindWA.insertAt(this.body, ta.selectionStart, ta.selectionEnd, "{{" + key + "}}");
      this._apply(r, r.cursor, r.cursor);
    },
    wrap(marker) {
      if (this.readOnly) return;
      const ta = this.$refs.body;
      const r = window.EFindWA.wrapSelection(this.body, ta.selectionStart, ta.selectionEnd, marker);
      this._apply(r, r.selectionStart, r.selectionEnd);
    },
    addOptOut() {
      if (this.readOnly) return;
      this.body = window.EFindWA.appendOptOut(this.body, this.optOutInstruction);
      this.$nextTick(() => {
        const ta = this.$refs.body;
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
        ta.scrollTop = ta.scrollHeight;
      });
    },

    // ---------------------------------------------------------- parâmetros do template oficial
    addRow() {
      if (this.rows.length < 20 && this.variables.length) this.rows.push(this.variables[0].key);
    },
    removeRow(i) {
      this.rows.splice(i, 1);
    },
    moveRow(i, delta) {
      const j = i + delta;
      if (j < 0 || j >= this.rows.length) return;
      const copy = [...this.rows];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      this.rows = copy;
    },

    // ---------------------------------------------------------- pré-visualização
    renderPreview() {
      const el = this.$refs.preview;
      if (!el) return;
      const text = window.EFindWA.renderTemplate(this.body, this.example);
      if (!text.trim() && !this.mediaLabel) {
        el.replaceChildren();
        return;
      }
      window.EFindWA.showChat(el, text, this.mediaLabel);
    },
  }));
});
