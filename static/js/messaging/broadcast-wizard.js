/* Assistente de novo disparo (Alpine): mensagem → público → envio → revisão.
 * Os campos visíveis não têm "name": o formulário real (#wizard-form) recebe campos ocultos preenchidos pelo estado.
 * O servidor revalida TUDO (modelo/conexão da campanha, público dentro do escopo, agendamento, consentimento). */
document.addEventListener("alpine:init", () => {
  const SAO_PAULO = "America/Sao_Paulo";

  /** Agora no fuso de Brasília no formato do <input type="datetime-local"> ("2026-10-20T14:30") */
  function nowLocal() {
    try {
      const parts = new Intl.DateTimeFormat("sv-SE", {
        timeZone: SAO_PAULO,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(new Date());
      return parts.replace(" ", "T");
    } catch (e) {
      return new Date().toISOString().slice(0, 16);
    }
  }

  window.Alpine.data("broadcastWizard", (config) => ({
    steps: ["Mensagem", "Público", "Envio", "Revisão"],
    step: config.step || 0,
    furthest: config.step || 0,
    templates: config.templates || [],
    connections: config.connections || [],
    urls: config.urls || {},
    canViewTemplates: !!config.canViewTemplates,
    example: config.example || {},
    form: { ...config.state },
    errors: { ...(config.errors || {}) },
    audience: null,
    audienceLoading: false,
    audienceError: "",
    review: null,
    reviewLoading: false,
    reviewError: "",
    submitting: false,
    minSchedule: nowLocal(),
    _timer: null,
    _controller: null,
    _reviewController: null,

    init() {
      this.$watch("form.template", () => this.renderTemplatePreview());
      this.$watch("form.connection", () => this.syncRate());
      this.$watch("step", (value) => {
        this.furthest = Math.max(this.furthest, value);
        this.minSchedule = nowLocal();
        window.scrollTo({ top: 0, behavior: "smooth" });
        if (value === 3) this.loadReview();
      });
      this.$nextTick(() => {
        this.renderTemplatePreview();
        if (this.step === 3) this.loadReview();
      });
      this.loadAudience();
    },

    // ---------------------------------------------------------- derivados
    get template() {
      return this.templates.find((t) => t.id === this.form.template) || null;
    },
    get connection() {
      return this.connections.find((c) => c.id === this.form.connection) || null;
    },
    get rateMax() {
      return this.connection ? this.connection.rate : 1000;
    },
    get rateNumber() {
      const n = Number(this.form.rate);
      return Number.isInteger(n) ? n : NaN;
    },
    get rateValid() {
      return this.rateNumber >= 1 && this.rateNumber <= this.rateMax;
    },
    get templateBlocked() {
      return !!(this.connection && this.template && this.connection.requiresTemplate && !this.template.providerTemplateName);
    },
    get scheduleError() {
      if (this.form.mode !== "schedule") return "";
      const value = (this.form.scheduledAt || "").trim();
      if (!value) return "Informe a data e a hora do envio.";
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return "Data ou hora inválida.";
      if (value <= nowLocal()) return "Escolha um horário no futuro.";
      return "";
    },
    get activeFilterCount() {
      return Object.keys(this.form.filters || {}).length;
    },

    stepValid(i) {
      if (i === 0) return this.form.name.trim().length >= 3 && !!this.template;
      if (i === 1) return !!this.audience && !this.audienceLoading && !this.audienceError && this.audience.eligible > 0;
      if (i === 2) return !!this.connection && !this.templateBlocked && this.rateValid && !this.scheduleError;
      if (i === 3) return !!this.form.consent && !!this.review && this.review.eligible > 0;
      return false;
    },
    allValid() {
      return [0, 1, 2, 3].every((i) => this.stepValid(i));
    },
    next() {
      if (this.step < 3 && this.stepValid(this.step)) this.step += 1;
    },
    back() {
      if (this.step > 0) this.step -= 1;
    },
    go(i) {
      if (i <= this.furthest && i !== this.step) this.step = i;
    },
    fmt(n) {
      return Number(n || 0).toLocaleString("pt-BR");
    },
    voters(n) {
      return this.fmt(n) + (Number(n) === 1 ? " apoiador" : " apoiadores");
    },

    // ---------------------------------------------------------- etapa 1: mensagem
    renderTemplatePreview() {
      const el = this.$refs.tplPreview;
      if (!el) return;
      const t = this.template;
      if (!t) {
        el.replaceChildren();
        return;
      }
      const media = t.type !== "TEXT" ? t.typeLabel : "";
      window.EFindWA.showChat(el, window.EFindWA.renderTemplate(t.body, this.example), media);
    },

    // ---------------------------------------------------------- etapa 2: público
    onFiltersChanged() {
      this.$nextTick(() => this.readFilters());
    },
    readFilters() {
      const root = this.$refs.filters;
      const formEl = root && root.querySelector("form");
      if (!formEl) return;
      const filters = window.EFind.paramsToFilters(new URLSearchParams(new FormData(formEl)));
      delete filters.messageable;
      if (typeof filters.q === "string") {
        filters.q = filters.q.trim();
        if (!filters.q) delete filters.q;
      }
      for (const key of ["age_min", "age_max"]) {
        if (typeof filters[key] === "number" && Number.isNaN(filters[key])) delete filters[key];
      }
      if (JSON.stringify(filters) === JSON.stringify(this.form.filters)) return;
      this.form.filters = filters;
      delete this.errors.filters;
      this.review = null;
      this.queueAudience();
    },
    onFilterClick(event) {
      const link = event.target.closest && event.target.closest("a");
      if (link && link.getAttribute("href") === "#") {
        event.preventDefault();
        this.clearFilters();
      }
    },
    clearFilters() {
      const root = this.$refs.filters;
      if (!root) return;
      root.querySelectorAll('[x-data^="multiSelect"]').forEach((el) => {
        const data = window.Alpine.$data(el);
        if (data && typeof data.clear === "function") data.clear();
      });
      root.querySelectorAll("input, select").forEach((el) => {
        if (el.type === "checkbox") el.checked = false;
        else if (el.type !== "hidden") el.value = "";
      });
      this.onFiltersChanged();
    },
    queueAudience() {
      clearTimeout(this._timer);
      this.audienceLoading = true;
      this._timer = setTimeout(() => this.loadAudience(), 400);
    },
    async loadAudience() {
      if (this._controller) this._controller.abort();
      const controller = new AbortController();
      this._controller = controller;
      this.audienceLoading = true;
      try {
        const params = window.EFind.filtersToParams(this.form.filters);
        const res = await fetch(this.urls.audience + "?" + params.toString(), {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          signal: controller.signal,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "Não foi possível contar o público. Tente de novo.");
        this.audience = data;
        this.audienceError = "";
      } catch (err) {
        if (err.name === "AbortError") return;
        this.audience = null;
        this.audienceError = err.message || "Não foi possível contar o público.";
      } finally {
        if (this._controller === controller) this.audienceLoading = false;
      }
    },

    // ---------------------------------------------------------- etapa 3: envio
    syncRate() {
      const c = this.connection;
      if (!c) return;
      const current = this.rateNumber;
      if (!Number.isFinite(current) || current > c.rate) this.form.rate = Math.min(20, c.rate);
      delete this.errors.connection;
    },
    pickMode(mode) {
      this.form.mode = mode;
      delete this.errors.mode;
      delete this.errors.scheduled_at;
      this.minSchedule = nowLocal();
    },

    // ---------------------------------------------------------- etapa 4: revisão
    async loadReview() {
      if (this._reviewController) this._reviewController.abort();
      const controller = new AbortController();
      this._reviewController = controller;
      this.reviewLoading = true;
      this.reviewError = "";
      try {
        const params = window.EFind.filtersToParams(this.form.filters);
        params.set("detalhe", "1");
        params.set("modelo", this.form.template);
        params.set("velocidade", String(this.form.rate));
        const res = await fetch(this.urls.audience + "?" + params.toString(), {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          signal: controller.signal,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "Não foi possível montar a revisão. Tente de novo.");
        this.review = data;
        this.$nextTick(() => this.renderSamples());
      } catch (err) {
        if (err.name === "AbortError") return;
        this.review = null;
        this.reviewError = err.message || "Não foi possível montar a revisão.";
      } finally {
        if (this._reviewController === controller) this.reviewLoading = false;
      }
    },
    renderSamples() {
      const el = this.$refs.samples;
      if (!el) return;
      const samples = (this.review && this.review.samples) || [];
      const media = this.template && this.template.type !== "TEXT" ? this.template.typeLabel : "";
      let texts = samples.map((s) => s.body);
      // Sem destinatários de exemplo: mostra o modelo com os dados fictícios
      if (!texts.length && this.template) texts = [window.EFindWA.renderTemplate(this.template.body, this.example)];
      window.EFindWA.showChat(el, texts, media);
    },
    get whenLabel() {
      if (this.form.mode !== "schedule") return "Assim que você confirmar";
      const v = this.form.scheduledAt;
      const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(v || "");
      return m ? m[3] + "/" + m[2] + "/" + m[1] + " às " + m[4] + ":" + m[5] + " (horário de Brasília)" : "—";
    },
  }));
});
