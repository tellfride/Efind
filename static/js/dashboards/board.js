/* E-Find — Dashboards: grade de widgets (carregamento dos dados, estados e edição).
 *
 * Board(opts):
 *   grid    elemento que recebe os widgets (grade de 1/2/4 colunas)
 *   config  objeto de {% json_script %} (widgets, catalog, dataUrl, csrf, sizes...)
 *   editable  mostra a barra de edição em cada widget (arrastar, subir/descer, tamanho, configurar, remover)
 *   hooks   { change(), settings(widgetId), busy(bool), loaded(), refreshFailed(message) }
 *
 * Os dados vêm de POST config.dataUrl ({widgets:[...]} → {id: dados | {error}}); o servidor aplica o escopo
 * hierárquico do usuário. Cada widget tem estado próprio (carregando / pronto / erro) e gráficos são destruídos
 * antes de redesenhar.
 */
(function () {
  "use strict";

  const D = window.EFindDash;
  const { el, icon } = D;

  // Colunas por tamanho: celular 1 coluna, tablet 2, desktop 4 (sm=1, md=2, lg=3, full=4)
  const SIZE_CLASSES = {
    sm: "",
    md: "md:col-span-2",
    lg: "md:col-span-2 xl:col-span-3",
    full: "md:col-span-2 xl:col-span-4",
  };
  const SIZE_TOKENS = ["md:col-span-2", "xl:col-span-3", "xl:col-span-4"];
  const FRAME = "relative flex min-w-0 flex-col rounded-xl border border-slate-200 bg-white shadow-sm transition-shadow";
  const TOOL_BTN =
    "inline-flex size-8 shrink-0 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-white hover:text-slate-900 hover:shadow-sm focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-35";
  const SIZE_ON = "bg-brand-600 text-white shadow-sm";
  const SIZE_OFF = "text-slate-600 hover:bg-white hover:text-slate-900";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function randomId() {
    const bytes = new Uint8Array(5);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    return "w" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  function hasFilters(widget) {
    const f = widget.config && widget.config.filters;
    return !!f && Object.keys(f).length > 0;
  }

  // Parte da configuração que muda os DADOS (título, tamanho e texto não precisam de nova consulta)
  function dataKey(widget, def) {
    const o = (def && def.options) || {};
    const c = widget.config || {};
    return JSON.stringify([widget.type, o.period ? c.period : null, o.limit ? c.limit : null, o.filters ? c.filters || null : null]);
  }

  class Board {
    constructor(opts) {
      this.grid = opts.grid;
      this.cfg = opts.config;
      this.editable = !!opts.editable;
      this.hooks = opts.hooks || {};
      this.maxWidgets = (this.cfg.limits && this.cfg.limits.widgets) || 30;
      this.catalog = {};
      (this.cfg.catalog || []).forEach((c) => {
        this.catalog[c.type] = c;
      });
      this.widgets = clone(this.cfg.widgets || []).filter((w) => this.catalog[w.type]);
      this.nodes = {};
      this.data = {};
      this.state = {};
      this.errors = {};
      this.seq = {};
      this.charts = {};
      this.counter = 0;
      this.inflight = 0;
      this.grid.addEventListener("click", (e) => this.onClick(e));
    }

    // -------------------------------------------------------------- Consulta
    find(id) {
      return this.widgets.find((w) => w.id === id);
    }

    getWidgets() {
      return clone(this.widgets);
    }

    // -------------------------------------------------------------- Desenho
    render() {
      Object.keys(this.charts).forEach((id) => this.destroyCharts(id));
      this.grid.replaceChildren();
      this.nodes = {};
      this.widgets.forEach((w) => {
        const node = this.buildWidget(w);
        this.nodes[w.id] = node;
        this.grid.append(node);
        this.paint(w.id);
      });
      this.updateEmpty();
      this.refreshToolbars();
    }

    updateEmpty() {
      let placeholder = this.grid.querySelector(":scope > [data-empty]");
      if (this.widgets.length) {
        if (placeholder) placeholder.remove();
        return;
      }
      if (placeholder) return;
      placeholder = D.emptyBlock(
        "layout-grid",
        "Este dashboard ainda não tem widgets",
        this.editable ? "Use o botão “Adicionar widget” para escolher indicadores, rankings e gráficos." : "Quem administra o dashboard pode adicionar widgets.",
      );
      placeholder.dataset.empty = "1";
      placeholder.className += " col-span-full rounded-xl border border-dashed border-slate-300 bg-white py-12";
      this.grid.append(placeholder);
    }

    titleOf(widget) {
      const def = this.catalog[widget.type];
      return (widget.config && widget.config.title) || (def ? def.label : widget.type);
    }

    subtitleOf(widget) {
      const def = this.catalog[widget.type];
      const parts = [];
      if (def && def.options && def.options.period) parts.push(D.periodLabel((widget.config && widget.config.period) || 30));
      if (hasFilters(widget)) parts.push("Filtrado");
      return parts.join(" · ");
    }

    buildWidget(widget) {
      const def = this.catalog[widget.type];
      const node = el("article", FRAME + " " + (SIZE_CLASSES[widget.size] || ""));
      node.dataset.widgetId = widget.id;
      node.dataset.type = widget.type;
      const subtitle = this.subtitleOf(widget);
      const head = el("header", "flex items-start gap-3 px-4 pt-4", [
        el("div", "flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600", icon(def.icon, "size-5")),
        el("div", "min-w-0 flex-1", [
          el("h3", "truncate text-sm font-semibold text-slate-900", this.titleOf(widget)),
          subtitle ? el("p", "truncate text-xs text-slate-500", subtitle) : null,
        ]),
      ]);
      const body = el("div", "@container min-w-0 flex-1 px-4 pt-3 pb-4");
      body.dataset.body = "1";
      node.append(head, body);
      if (this.editable) node.append(this.buildToolbar(widget));
      return node;
    }

    toolButton(act, iconName, label, extra) {
      const btn = el("button", TOOL_BTN + (extra ? " " + extra : ""), icon(iconName, "size-4"));
      btn.type = "button";
      btn.dataset.act = act;
      btn.setAttribute("aria-label", label);
      btn.title = label;
      return btn;
    }

    buildToolbar(widget) {
      const bar = el("div", "flex flex-wrap items-center gap-1 rounded-b-xl border-t border-slate-100 bg-slate-50 px-2 py-1.5");
      bar.dataset.toolbar = "1";
      const handle = this.toolButton("handle", "grip-vertical", "Arrastar para reordenar", "dash-handle cursor-grab touch-none active:cursor-grabbing");
      handle.removeAttribute("data-act");
      bar.append(
        handle,
        this.toolButton("up", "arrow-up", "Mover para cima"),
        this.toolButton("down", "arrow-down", "Mover para baixo"),
      );
      const sizes = el("div", "ml-1 inline-flex items-center gap-0.5 rounded-lg border border-slate-200 bg-slate-100/70 p-0.5");
      sizes.setAttribute("role", "group");
      sizes.setAttribute("aria-label", "Tamanho do widget");
      (this.cfg.sizes || []).forEach((s) => {
        const btn = el("button", "h-7 min-w-7 rounded-md px-2 text-xs font-semibold transition-colors " + (s.value === widget.size ? SIZE_ON : SIZE_OFF), s.short);
        btn.type = "button";
        btn.dataset.act = "size";
        btn.dataset.size = s.value;
        btn.title = s.long;
        btn.setAttribute("aria-label", "Tamanho: " + s.long);
        btn.setAttribute("aria-pressed", s.value === widget.size ? "true" : "false");
        sizes.append(btn);
      });
      bar.append(sizes, el("span", "flex-1"));
      bar.append(
        this.toolButton("settings", "sliders-horizontal", "Configurar widget"),
        this.toolButton("remove", "trash-2", "Remover widget", "hover:text-red-600"),
      );
      return bar;
    }

    refreshToolbars() {
      if (!this.editable) return;
      this.widgets.forEach((w, i) => {
        const node = this.nodes[w.id];
        if (!node) return;
        const up = node.querySelector('[data-act="up"]');
        const down = node.querySelector('[data-act="down"]');
        if (up) up.disabled = i === 0;
        if (down) down.disabled = i === this.widgets.length - 1;
      });
    }

    paint(id) {
      const node = this.nodes[id];
      const widget = this.find(id);
      if (!node || !widget) return;
      const body = node.querySelector("[data-body]");
      this.destroyCharts(id);
      body.replaceChildren();
      const state = widget.type === "note" ? "ready" : this.state[id] || "loading";
      if (state === "loading") {
        body.append(D.skeleton(widget.type));
        return;
      }
      if (state === "error") {
        body.append(D.errorBlock(this.errors[id], () => this.load([id])));
        return;
      }
      const render = D.renderers[widget.type];
      try {
        render(body, this.data[id] || {}, widget, { track: (chart) => this.track(id, chart), editable: this.editable });
      } catch (err) {
        this.destroyCharts(id);
        body.replaceChildren(D.errorBlock("Não foi possível exibir este widget.", () => this.paint(id)));
      }
    }

    track(id, chart) {
      (this.charts[id] = this.charts[id] || []).push(chart);
    }

    destroyCharts(id) {
      (this.charts[id] || []).forEach((chart) => {
        try {
          chart.destroy();
        } catch (e) {
          /* gráfico já destruído */
        }
      });
      delete this.charts[id];
    }

    destroy() {
      Object.keys(this.charts).forEach((id) => this.destroyCharts(id));
    }

    // -------------------------------------------------------------- Dados
    setBusy(delta) {
      this.inflight += delta;
      if (this.hooks.busy) this.hooks.busy(this.inflight > 0);
    }

    /** Busca os dados de `ids` (todos, se omitido). `silent`: mantém o conteúdo atual enquanto atualiza. */
    async load(ids, opts) {
      const silent = !!(opts && opts.silent);
      const targets = this.widgets.filter((w) => !ids || ids.includes(w.id));
      const fetchList = [];
      targets.forEach((w) => {
        if (w.type === "note") return; // recado: texto da própria configuração, sem consulta
        fetchList.push(w);
        this.seq[w.id] = ++this.counter;
        if (!silent || !this.data[w.id]) {
          this.state[w.id] = "loading";
          this.paint(w.id);
        }
      });
      if (!fetchList.length) return true;
      const tokens = {};
      fetchList.forEach((w) => {
        tokens[w.id] = this.seq[w.id];
      });

      this.setBusy(1);
      let payload = null;
      let failure = "";
      try {
        const res = await fetch(this.cfg.dataUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": this.cfg.csrf },
          body: JSON.stringify({ widgets: fetchList.map((w) => ({ id: w.id, type: w.type, size: w.size, config: w.config })) }),
        });
        const json = await res.json().catch(() => ({}));
        if (res.status === 401) failure = "Sua sessão expirou. Entre novamente para ver os dados.";
        else if (!res.ok) failure = json.error || "Não foi possível carregar os dados agora.";
        else payload = json;
      } catch (err) {
        failure = "Sem conexão com o servidor. Verifique sua internet e tente novamente.";
      } finally {
        this.setBusy(-1);
      }

      let ok = true;
      fetchList.forEach((w) => {
        if (this.seq[w.id] !== tokens[w.id] || !this.nodes[w.id]) return; // resposta antiga (widget alterado/removido)
        const item = payload ? payload[w.id] : null;
        if (item && !item.error) {
          this.data[w.id] = item;
          this.state[w.id] = "ready";
        } else {
          ok = false;
          const message = (item && item.error) || failure || "Não foi possível carregar este widget.";
          if (silent && this.data[w.id]) {
            this.state[w.id] = "ready"; // mantém os dados antigos na tela
          } else {
            this.state[w.id] = "error";
            this.errors[w.id] = message;
          }
          if (silent && this.hooks.refreshFailed) this.hooks.refreshFailed(message);
        }
        this.paint(w.id);
      });
      if (ok && this.hooks.loaded) this.hooks.loaded();
      return ok;
    }

    // -------------------------------------------------------------- Edição
    notify() {
      this.updateEmpty();
      this.refreshToolbars();
      if (this.hooks.change) this.hooks.change();
    }

    canAdd() {
      return this.widgets.length < this.maxWidgets;
    }

    typeCount(type) {
      return this.widgets.filter((w) => w.type === type).length;
    }

    newWidget(type) {
      const def = this.catalog[type];
      const o = def.options || {};
      const config = {};
      if (o.period) config.period = 30;
      if (o.limit) config.limit = o.limit.default;
      if (o.text) config.text = "";
      return { id: randomId(), type, size: def.default_size, config };
    }

    addWidget(type) {
      if (!this.catalog[type] || !this.canAdd()) return null;
      const widget = this.newWidget(type);
      this.widgets.push(widget);
      const node = this.buildWidget(widget);
      this.nodes[widget.id] = node;
      const placeholder = this.grid.querySelector(":scope > [data-empty]");
      if (placeholder) placeholder.remove();
      this.grid.append(node);
      this.paint(widget.id);
      this.notify();
      this.load([widget.id]);
      return widget;
    }

    removeWidget(id) {
      const node = this.nodes[id];
      this.destroyCharts(id);
      if (node) node.remove();
      delete this.nodes[id];
      delete this.data[id];
      delete this.state[id];
      delete this.errors[id];
      delete this.seq[id];
      this.widgets = this.widgets.filter((w) => w.id !== id);
      this.notify();
    }

    moveWidget(id, delta) {
      const from = this.widgets.findIndex((w) => w.id === id);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= this.widgets.length) return;
      const [item] = this.widgets.splice(from, 1);
      this.widgets.splice(to, 0, item);
      const node = this.nodes[id];
      if (delta < 0) {
        const before = this.nodes[this.widgets[to + 1].id];
        this.grid.insertBefore(node, before);
      } else {
        const after = this.nodes[this.widgets[to - 1].id];
        this.grid.insertBefore(node, after.nextSibling);
      }
      this.notify();
      const target = node.querySelector(delta < 0 ? '[data-act="up"]' : '[data-act="down"]');
      const fallback = node.querySelector(delta < 0 ? '[data-act="down"]' : '[data-act="up"]');
      const focusEl = target && !target.disabled ? target : fallback;
      if (focusEl) focusEl.focus({ preventScroll: true });
      node.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    /** Lê a ordem atual do DOM (depois de arrastar) e atualiza a lista. */
    syncOrderFromDom() {
      const ids = Array.from(this.grid.querySelectorAll(":scope > [data-widget-id]")).map((n) => n.dataset.widgetId);
      const byId = new Map(this.widgets.map((w) => [w.id, w]));
      const next = ids.map((id) => byId.get(id)).filter(Boolean);
      if (next.length !== this.widgets.length) return;
      this.widgets = next;
      this.notify();
    }

    setSize(id, size) {
      const widget = this.find(id);
      const node = this.nodes[id];
      if (!widget || !node || !(size in SIZE_CLASSES)) return;
      widget.size = size;
      SIZE_TOKENS.forEach((t) => node.classList.remove(t));
      SIZE_CLASSES[size]
        .split(" ")
        .filter(Boolean)
        .forEach((t) => node.classList.add(t));
      node.querySelectorAll('[data-act="size"]').forEach((btn) => {
        const on = btn.dataset.size === size;
        btn.className = "h-7 min-w-7 rounded-md px-2 text-xs font-semibold transition-colors " + (on ? SIZE_ON : SIZE_OFF);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
      });
      this.notify();
    }

    /** Aplica nova configuração; só consulta o servidor de novo quando algo que muda os dados foi alterado. */
    updateConfig(id, config) {
      const widget = this.find(id);
      const old = this.nodes[id];
      if (!widget || !old) return;
      const def = this.catalog[widget.type];
      const before = dataKey(widget, def);
      widget.config = clone(config);
      const fresh = this.buildWidget(widget);
      this.destroyCharts(id);
      old.replaceWith(fresh);
      this.nodes[id] = fresh;
      if (widget.type !== "note" && (before !== dataKey(widget, def) || !this.data[id])) this.load([id]);
      else this.paint(id);
      this.refreshToolbars();
      this.notify();
    }

    /** Substitui toda a lista (ex.: descartar alterações) e recarrega os dados. */
    replaceAll(widgets) {
      this.widgets = clone(widgets).filter((w) => this.catalog[w.type]);
      this.data = {};
      this.state = {};
      this.errors = {};
      this.render();
      this.load();
    }

    flash(id) {
      const node = this.nodes[id];
      if (!node) return;
      node.scrollIntoView({ behavior: "smooth", block: "center" });
      node.classList.add("ring-2", "ring-brand-500");
      setTimeout(() => node.classList.remove("ring-2", "ring-brand-500"), 1600);
    }

    // -------------------------------------------------------------- Eventos da barra de edição
    onClick(event) {
      if (!this.editable) return;
      const btn = event.target.closest("[data-act]");
      if (!btn || !this.grid.contains(btn)) return;
      const node = btn.closest("[data-widget-id]");
      if (!node) return;
      const id = node.dataset.widgetId;
      const act = btn.dataset.act;
      if (act === "up") this.moveWidget(id, -1);
      else if (act === "down") this.moveWidget(id, 1);
      else if (act === "size") this.setSize(id, btn.dataset.size);
      else if (act === "settings" && this.hooks.settings) this.hooks.settings(id);
      else if (act === "remove") {
        if (window.confirm("Remover o widget “" + this.titleOf(this.find(id)) + "” deste dashboard?")) this.removeWidget(id);
      }
    }
  }

  D.Board = Board;
  D.clone = clone;
})();
