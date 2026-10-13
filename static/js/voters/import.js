/* E-Find · importação de eleitores por CSV.
 * O navegador só LÊ o arquivo (FileReader) e mostra a análise; toda leitura, mapeamento e validação são feitas
 * pelo servidor (POST em previewUrl para a pré-visualização e novamente no envio final). */
(function () {
  "use strict";

  function emptyAnalysis() {
    return {
      missing_required: [],
      over_limit: false,
      total_rows: 0,
      fields_used: [],
      preview: [],
      ready: false,
      summary: { valid: 0, invalid: 0, repeated_in_file: 0, already_registered: 0, will_import: 0, with_warnings: 0 },
    };
  }

  function csrfToken(root) {
    const input = root.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  document.addEventListener("alpine:init", () => {
    window.Alpine.data("voterImport", () => ({
      cfg: {},
      fields: [],
      text: "",
      fileName: "",
      hasHeader: true,
      mapping: [],
      columns: [],
      analysis: emptyAnalysis(),
      analyzed: false,
      loading: false,
      error: "",
      reqId: 0,

      init() {
        const node = document.getElementById("import-config");
        this.cfg = node ? JSON.parse(node.textContent) : {};
        this.fields = this.cfg.fields || [];
        const ini = this.cfg.initial || {};
        if (ini.text) {
          this.text = ini.text;
          this.analyze({ mapping: Array.isArray(ini.mapping) ? ini.mapping : null, header: ini.hasHeader });
        }
      },

      get canSubmit() {
        return this.analyzed && !this.loading && this.analysis.ready && !this.analysis.over_limit && !this.analysis.missing_required.length;
      },
      get submitLabel() {
        const n = this.analysis.summary.will_import;
        return this.canSubmit ? "Importar " + n + " eleitor" + (n === 1 ? "" : "es") : "Importar eleitores";
      },

      onFile(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        if (file.size > 6 * 1024 * 1024) {
          this.error = "Arquivo muito grande. Divida a lista em arquivos menores (até 5.000 linhas).";
          return;
        }
        const reader = new FileReader();
        reader.onload = () => {
          let decoded;
          try {
            decoded = new TextDecoder("utf-8", { fatal: true }).decode(reader.result);
          } catch (e) {
            decoded = new TextDecoder("windows-1252").decode(reader.result); // CSV do Excel em português
          }
          this.fileName = file.name;
          this.text = decoded;
          this.analyze({});
        };
        reader.onerror = () => {
          this.error = "Não foi possível ler o arquivo.";
        };
        reader.readAsArrayBuffer(file);
      },

      onPaste() {
        this.fileName = "";
        if (!this.text.trim()) return this.reset();
        this.analyze({});
      },

      reset() {
        this.text = "";
        this.fileName = "";
        this.mapping = [];
        this.columns = [];
        this.analysis = emptyAnalysis();
        this.analyzed = false;
        this.error = "";
        const input = document.getElementById("import-file");
        if (input) input.value = "";
      },

      setMapping(index, key) {
        const next = [...this.mapping];
        next[index] = key;
        this.mapping = next;
        this.analyze({ mapping: next, header: this.hasHeader });
      },

      toggleHeader(value) {
        this.hasHeader = value;
        this.analyze({ header: value });
      },

      // opts.mapping: lista (mantém o mapeamento do usuário) | opts.header: força cabeçalho sim/não
      async analyze(opts) {
        if (this.text.length > (this.cfg.maxChars || 1500000)) {
          this.error = "Arquivo muito grande. Divida a lista em arquivos menores (até " + (this.cfg.maxRows || 5000) + " linhas).";
          return;
        }
        const id = ++this.reqId;
        this.loading = true;
        this.error = "";
        const body = { csv_text: this.text };
        if (opts && Array.isArray(opts.mapping)) body.mapping = opts.mapping;
        if (opts && typeof opts.header === "boolean") body.has_header = opts.header;
        try {
          const res = await fetch(this.cfg.previewUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(this.$root), Accept: "application/json" },
            body: JSON.stringify(body),
            credentials: "same-origin",
          });
          const data = await res.json().catch(() => ({}));
          if (id !== this.reqId) return; // resposta de uma análise antiga
          if (!res.ok) {
            this.error = data.error || "Não foi possível analisar o arquivo.";
            this.analyzed = false;
            return;
          }
          this.hasHeader = data.has_header;
          this.mapping = data.mapping;
          this.columns = data.columns;
          this.analysis = { ...emptyAnalysis(), ...data, summary: { ...emptyAnalysis().summary, ...(data.summary || {}) } };
          this.analyzed = true;
        } catch (e) {
          if (id === this.reqId) this.error = "Falha de conexão ao analisar o arquivo. Tente novamente.";
        } finally {
          if (id === this.reqId) this.loading = false;
        }
      },

      onSubmit(ev) {
        if (!this.canSubmit) ev.preventDefault();
      },
    }));
  });
})();
