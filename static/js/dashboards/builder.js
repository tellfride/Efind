/* E-Find — Dashboards: montador (/painel/dashboards/<id>/editar/).
 * Componente Alpine `dashboardBuilder`: adicionar/configurar/reordenar/remover widgets com pré-visualização dos
 * dados reais, campos do dashboard e salvamento (POST JSON validado no servidor por validate_widgets). */
(function () {
  "use strict";

  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function normalize(text) {
    return String(text || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();
  }

  function trapFocus(event, dialog) {
    if (event.key !== "Tab" || !dialog) return;
    const items = Array.from(dialog.querySelectorAll(FOCUSABLE)).filter((n) => n.offsetParent !== null);
    if (!items.length) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  document.addEventListener("alpine:init", () => {
    window.Alpine.data("dashboardBuilder", () => {
      // Fora da reatividade do Alpine (objetos grandes, instâncias de bibliotecas)
      let cfg = null;
      let board = null;
      let saved = "";
      let opener = null;
      let filtersToken = 0;

      return {
        // dashboard
        name: "",
        description: "",
        shared: false,
        campaignDefault: false,
        isAdmin: false,
        dirty: false,
        saving: false,
        busy: false,
        count: 0,
        maxWidgets: 30,
        groups: [],
        periods: [],
        // modal "adicionar widget"
        addOpen: false,
        query: "",
        // modal "configurar widget"
        st: { open: false, id: "", type: "", label: "", options: {}, title: "", period: 30, limit: 10, text: "", filters: {} },
        filtersState: "idle",

        init() {
          const node = document.getElementById("dash-config");
          const grid = this.$root.querySelector("[data-dash-grid]");
          if (!node || !grid || !window.EFindDash) return;
          cfg = JSON.parse(node.textContent);
          const d = cfg.dashboard || {};
          this.name = d.name || "";
          this.description = d.description || "";
          this.shared = !!d.shared;
          this.campaignDefault = !!d.campaignDefault;
          this.isAdmin = !!cfg.isAdmin;
          this.maxWidgets = (cfg.limits && cfg.limits.widgets) || 30;
          this.periods = cfg.periods || [];
          this.groups = (cfg.groups || [])
            .map((g) => ({ key: g.key, label: g.label, items: cfg.catalog.filter((c) => c.group === g.key) }))
            .filter((g) => g.items.length);

          board = new window.EFindDash.Board({
            grid,
            config: cfg,
            editable: true,
            hooks: {
              change: () => this.onBoardChange(),
              settings: (id) => this.openSettings(id),
              busy: (value) => {
                this.busy = value;
              },
            },
          });
          board.render();
          board.load();
          this.count = board.widgets.length;
          saved = this.snapshot();

          if (window.Sortable) {
            window.Sortable.create(grid, {
              handle: ".dash-handle",
              draggable: "[data-widget-id]",
              animation: 160,
              ghostClass: "opacity-40",
              chosenClass: "shadow-xl",
              delayOnTouchOnly: true,
              delay: 120,
              onEnd: () => board.syncOrderFromDom(),
            });
          }

          this.$watch("name", () => this.refreshDirty());
          this.$watch("description", () => this.refreshDirty());
          this.$watch("shared", (value) => {
            if (!value && this.campaignDefault) this.campaignDefault = false;
            this.refreshDirty();
          });
          this.$watch("campaignDefault", (value) => {
            if (value) this.shared = true;
            this.refreshDirty();
          });
          this.$watch("addOpen", (open) => this.lockScroll(open));
          this.$watch("st.open", (open) => this.lockScroll(open));
          window.addEventListener("beforeunload", (event) => {
            if (this.dirty) {
              event.preventDefault();
              event.returnValue = "";
            }
          });
        },

        // ---------------------------------------------------------- Estado
        snapshot() {
          return JSON.stringify({
            n: this.name.trim(),
            d: this.description.trim(),
            s: this.shared,
            c: this.campaignDefault,
            w: board.getWidgets(),
          });
        },
        refreshDirty() {
          if (board) this.dirty = this.snapshot() !== saved;
        },
        onBoardChange() {
          this.count = board.widgets.length;
          this.refreshDirty();
        },
        lockScroll(open) {
          if (open) document.body.classList.add("overflow-hidden");
          else if (!this.addOpen && !this.st.open) document.body.classList.remove("overflow-hidden");
        },
        leave(event) {
          if (this.dirty && !window.confirm("Há alterações não salvas. Sair mesmo assim?")) event.preventDefault();
        },
        trap(event) {
          trapFocus(event, event.currentTarget);
        },

        // ---------------------------------------------------------- Adicionar widget
        openAdd(event) {
          opener = (event && event.currentTarget) || document.activeElement;
          this.query = "";
          this.addOpen = true;
          this.$nextTick(() => {
            if (this.$refs.addSearch) this.$refs.addSearch.focus();
          });
        },
        closeAdd() {
          this.addOpen = false;
          if (opener && opener.focus) opener.focus({ preventScroll: true });
        },
        get filteredGroups() {
          const q = normalize(this.query);
          if (!q) return this.groups;
          return this.groups
            .map((g) => ({ ...g, items: g.items.filter((i) => normalize(i.label + " " + i.description).includes(q)) }))
            .filter((g) => g.items.length);
        },
        get atLimit() {
          return this.count >= this.maxWidgets;
        },
        iconHtml(name, cls) {
          return window.EFindDash.iconHtml(name, cls);
        },
        pick(item) {
          if (!item.available || this.atLimit) return;
          const widget = board.addWidget(item.type);
          this.addOpen = false;
          if (widget) {
            window.EFind.toast("Widget “" + item.label + "” adicionado ao final do dashboard.", "success");
            this.$nextTick(() => board.flash(widget.id));
          }
        },

        // ---------------------------------------------------------- Configurar widget
        openSettings(id) {
          const widget = board.find(id);
          const item = widget && cfg.catalog.find((c) => c.type === widget.type);
          if (!item) return;
          opener = document.activeElement;
          const c = widget.config || {};
          const o = item.options || {};
          this.st = {
            open: true,
            id,
            type: widget.type,
            label: item.label,
            options: o,
            title: c.title || "",
            period: c.period || 30,
            limit: c.limit || (o.limit ? o.limit.default : 0),
            text: c.text || "",
            filters: JSON.parse(JSON.stringify(c.filters || {})),
          };
          this.filtersState = o.filters ? "loading" : "idle";
          this.$nextTick(() => {
            if (this.$refs.settingsDialog) this.$refs.settingsDialog.focus();
            if (o.filters) this.loadFilters(this.st.filters);
          });
        },
        closeSettings() {
          this.st.open = false;
          filtersToken += 1;
          if (this.$refs.filtersBox) this.$refs.filtersBox.replaceChildren();
          if (opener && opener.focus) opener.focus({ preventScroll: true });
        },
        async loadFilters(filters) {
          const token = ++filtersToken;
          this.filtersState = "loading";
          try {
            const qs = window.EFind.filtersToParams(filters || {}).toString();
            const res = await fetch(cfg.filtersUrl + (qs ? "?" + qs : ""), {
              credentials: "same-origin",
              headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (!res.ok) throw new Error("http " + res.status);
            const html = await res.text(); // fragmento do próprio servidor (templates com autoescape)
            if (token !== filtersToken || !this.st.open) return;
            this.$refs.filtersBox.innerHTML = html;
            this.filtersState = "ready";
          } catch (err) {
            if (token === filtersToken) this.filtersState = "error";
          }
        },
        onFiltersClick(event) {
          const link = event.target.closest("a");
          if (!link) return; // "Limpar" do painel de filtros
          event.preventDefault();
          this.st.filters = {};
          this.loadFilters({});
        },
        applySettings() {
          const st = this.st;
          const widget = board.find(st.id);
          if (!widget) {
            this.closeSettings();
            return;
          }
          const o = st.options || {};
          const limits = cfg.limits || {};
          const config = JSON.parse(JSON.stringify(widget.config || {}));
          const title = String(st.title || "").replace(/\s+/g, " ").trim().slice(0, limits.title || 80);
          if (title) config.title = title;
          else delete config.title;
          if (o.period) config.period = [7, 30, 90, 365].includes(Number(st.period)) ? Number(st.period) : 30;
          if (o.limit) {
            let n = parseInt(st.limit, 10);
            if (Number.isNaN(n)) n = o.limit.default;
            config.limit = Math.max(o.limit.min, Math.min(o.limit.max, n));
          }
          if (o.text) config.text = String(st.text || "").replace(/\r\n?/g, "\n").trim().slice(0, limits.note || 2000);
          if (o.filters && this.filtersState === "ready") {
            const form = this.$refs.filtersBox.querySelector("form");
            if (form) {
              const filters = window.EFind.paramsToFilters(new URLSearchParams(new FormData(form)));
              if (Object.keys(filters).length) config.filters = filters;
              else delete config.filters;
            }
          }
          board.updateConfig(st.id, config);
          this.closeSettings();
        },

        // ---------------------------------------------------------- Salvar / descartar
        async save() {
          if (this.saving) return;
          const name = this.name.trim();
          if (name.length < 2) {
            window.EFind.toast("Informe o nome do dashboard (mínimo de 2 caracteres).", "error");
            if (this.$refs.nameInput) this.$refs.nameInput.focus();
            return;
          }
          this.saving = true;
          try {
            const res = await fetch(cfg.saveUrl, {
              method: "POST",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": cfg.csrf },
              body: JSON.stringify({
                name,
                description: this.description.trim(),
                shared: this.shared,
                campaign_default: this.campaignDefault,
                widgets: board.getWidgets(),
              }),
            });
            const json = await res.json().catch(() => ({}));
            if (res.status === 401) {
              window.EFind.toast("Sua sessão expirou. Entre novamente para salvar.", "error");
              return;
            }
            if (!res.ok) {
              window.EFind.toast(json.error || "Não foi possível salvar o dashboard.", "error");
              return;
            }
            window.EFind.toast(json.message || "Dashboard salvo.", "success");
            if (json.redirect) {
              this.dirty = false;
              saved = this.snapshot();
              window.location.href = json.redirect;
              return;
            }
            if (json.dashboard) {
              this.name = json.dashboard.name;
              this.description = json.dashboard.description || "";
              this.shared = !!json.dashboard.shared;
              this.campaignDefault = !!json.dashboard.campaignDefault;
            }
            (json.widgets || []).forEach((w) => {
              const current = board.find(w.id);
              if (current && JSON.stringify(current.config) !== JSON.stringify(w.config)) board.updateConfig(w.id, w.config);
            });
            saved = this.snapshot();
            this.dirty = false;
          } catch (err) {
            window.EFind.toast("Sem conexão com o servidor. Suas alterações continuam na tela; tente salvar novamente.", "error");
          } finally {
            this.saving = false;
          }
        },
        discard() {
          if (!this.dirty) return;
          if (!window.confirm("Descartar todas as alterações não salvas?")) return;
          const s = JSON.parse(saved);
          this.name = s.n;
          this.description = s.d;
          this.shared = s.s;
          this.campaignDefault = s.c;
          board.replaceAll(s.w);
          this.count = board.widgets.length;
          this.dirty = false;
          window.EFind.toast("Alterações descartadas.", "info");
        },

        destroy() {
          if (board) board.destroy();
          document.body.classList.remove("overflow-hidden");
        },
      };
    });
  });
})();
