/* E-Find — comportamento global (Alpine, HTMX, toasts, máscaras, CEP). Sem dependências além de Alpine/HTMX. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ Toasts
  const toastState = { items: [], seq: 0 };

  function pushToast(message, level) {
    if (!message) return;
    const id = ++toastState.seq;
    toastState.items.push({ id, message, level: level || "info" });
    setTimeout(() => dismissToast(id), 6000);
    window.dispatchEvent(new CustomEvent("efind:toasts"));
  }
  function dismissToast(id) {
    toastState.items = toastState.items.filter((t) => t.id !== id);
    window.dispatchEvent(new CustomEvent("efind:toasts"));
  }
  window.EFind = window.EFind || {};
  window.EFind.toast = pushToast;

  // Mensagens do Django (renderizadas como <div data-toast data-level="..."> no HTML)
  function flushDjangoMessages() {
    document.querySelectorAll("[data-toast]").forEach((el) => {
      const level = { success: "success", error: "error", warning: "warning", info: "info", debug: "info" }[el.dataset.level] || "info";
      pushToast(el.textContent.trim(), level);
      el.remove();
    });
  }
  document.addEventListener("DOMContentLoaded", flushDjangoMessages);

  // HX-Trigger: {"toast": {"message": "...", "level": "success"}}
  document.addEventListener("toast", (e) => {
    const d = e.detail || {};
    pushToast(d.message || d.value, d.level);
  });

  // ------------------------------------------------------------------ Confirmação e cópia (delegação)
  document.addEventListener(
    "click",
    (e) => {
      const el = e.target.closest("[data-confirm]");
      // botão de submit dentro de form: a confirmação é feita no evento "submit" (evita perguntar duas vezes)
      if (el && el.tagName !== "FORM" && !(el.type === "submit" && el.form) && !window.confirm(el.dataset.confirm)) {
        e.preventDefault();
        e.stopImmediatePropagation();
        return;
      }
      const copy = e.target.closest("[data-copy]");
      if (copy) {
        navigator.clipboard
          .writeText(copy.dataset.copy)
          .then(() => pushToast("Copiado para a área de transferência", "success"))
          .catch(() => pushToast("Não foi possível copiar", "error"));
      }
    },
    true,
  );
  document.addEventListener(
    "submit",
    (e) => {
      const msg = (e.submitter && e.submitter.dataset.confirm) || e.target.dataset.confirm;
      if (msg && !window.confirm(msg)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    },
    true,
  );

  // ------------------------------------------------------------------ Máscaras
  function maskPhone(v) {
    const d = v.replace(/\D/g, "").slice(0, 11);
    if (d.length <= 2) return d.length ? "(" + d : "";
    if (d.length <= 6) return "(" + d.slice(0, 2) + ") " + d.slice(2);
    if (d.length <= 10) return "(" + d.slice(0, 2) + ") " + d.slice(2, 6) + "-" + d.slice(6);
    return "(" + d.slice(0, 2) + ") " + d.slice(2, 7) + "-" + d.slice(7);
  }
  function maskCep(v) {
    const d = v.replace(/\D/g, "").slice(0, 8);
    return d.length > 5 ? d.slice(0, 5) + "-" + d.slice(5) : d;
  }
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!(el instanceof HTMLInputElement)) return;
    if (el.dataset.mask === "phone") el.value = maskPhone(el.value);
    else if (el.dataset.mask === "cep") el.value = maskCep(el.value);
  });
  window.EFind.maskPhone = maskPhone;
  window.EFind.maskCep = maskCep;

  // ------------------------------------------------------------------ Preenchimento por CEP
  // <input data-mask="cep" data-cep-lookup data-cep-target="street:#id_street,neighborhood:#id_neighborhood,city:#id_city,state:#id_state">
  async function lookupCep(input) {
    const cep = input.value.replace(/\D/g, "");
    if (cep.length !== 8) return;
    const status = input.dataset.cepStatus ? document.querySelector(input.dataset.cepStatus) : null;
    if (status) status.textContent = "Buscando endereço...";
    try {
      const res = await fetch("/api/public/cep/" + cep + "/", { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(res.status === 404 ? "CEP não encontrado" : "Não foi possível consultar o CEP");
      const data = await res.json();
      (input.dataset.cepTarget || "").split(",").forEach((pair) => {
        const [key, selector] = pair.split(":");
        const target = selector && document.querySelector(selector);
        if (target && data[key] !== undefined && (data[key] || !target.value)) {
          target.value = data[key];
          target.dispatchEvent(new Event("input", { bubbles: true }));
        }
      });
      if (status) status.textContent = "";
      input.dispatchEvent(new CustomEvent("cep:found", { bubbles: true, detail: data }));
    } catch (err) {
      if (status) status.textContent = err.message;
      input.dispatchEvent(new CustomEvent("cep:error", { bubbles: true, detail: { message: err.message } }));
    }
  }
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (el instanceof HTMLInputElement && "cepLookup" in el.dataset && el.value.replace(/\D/g, "").length === 8) lookupCep(el);
  });

  // ------------------------------------------------------------------ Filtros de eleitores: formulário <-> JSON
  const FILTER_PARAMS = {
    q: ["q", "str"],
    bairro: ["neighborhoods", "list"],
    cidade: ["cities", "list"],
    cabo: ["registered_by_ids", "list"],
    coord: ["coordinator_ids", "list"],
    genero: ["genders", "list"],
    apoio: ["support_levels", "list"],
    origem: ["sources", "list"],
    tag: ["tags", "list"],
    zona: ["electoral_zones", "list"],
    idade_min: ["age_min", "int"],
    idade_max: ["age_max", "int"],
    de: ["created_from", "str"],
    ate: ["created_to", "str"],
    geo: ["has_geo", "bool"],
    whatsapp: ["messageable", "bool"],
  };
  // Converte parâmetros de URL (URLSearchParams/FormData) no dict de filtros usado pelo servidor
  window.EFind.paramsToFilters = function (params) {
    const out = {};
    for (const [param, [key, type]] of Object.entries(FILTER_PARAMS)) {
      const values = (params.getAll ? params.getAll(param) : []).filter((v) => v !== "" && v !== null);
      if (!values.length) continue;
      if (type === "list") out[key] = values;
      else if (type === "int") out[key] = parseInt(values[0], 10);
      else if (type === "bool") out[key] = values[0] === "1" || values[0] === "true";
      else out[key] = values[0];
    }
    return out;
  };
  // Converte o dict de filtros em URLSearchParams (para fetch/links)
  window.EFind.filtersToParams = function (filters) {
    const sp = new URLSearchParams();
    for (const [param, [key, type]] of Object.entries(FILTER_PARAMS)) {
      const v = filters && filters[key];
      if (v === undefined || v === null || v === "") continue;
      if (type === "list") v.forEach((item) => sp.append(param, item));
      else if (type === "bool") sp.set(param, v ? "1" : "0");
      else sp.set(param, String(v));
    }
    return sp;
  };

  // ------------------------------------------------------------------ Alpine
  document.addEventListener("alpine:init", () => {
    const Alpine = window.Alpine;

    Alpine.data("toasts", () => ({
      items: toastState.items,
      init() {
        window.addEventListener("efind:toasts", () => {
          this.items = [...toastState.items];
        });
      },
      dismiss(id) {
        dismissToast(id);
      },
    }));

    // Menu suspenso simples: <div x-data="dropdown" @click.outside="open=false">
    Alpine.data("dropdown", () => ({
      open: false,
      toggle() {
        this.open = !this.open;
      },
      close() {
        this.open = false;
      },
    }));

    // Seleção múltipla com busca. Gera <input type="hidden" name="..."> para cada item (GET/POST normais).
    //   <div x-data='multiSelect({name:"bairro", options:[{value,label,count,hint}], selected:["Centro"], placeholder:"Todos"})'>
    Alpine.data("multiSelect", (cfg) => ({
      name: cfg.name,
      options: cfg.options || [],
      selected: cfg.selected || [],
      placeholder: cfg.placeholder || "Selecione",
      searchPlaceholder: cfg.searchPlaceholder || "Buscar...",
      open: false,
      query: "",
      norm(s) {
        return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
      },
      get filtered() {
        const q = this.norm(this.query);
        return q ? this.options.filter((o) => this.norm(o.label + " " + (o.hint || "")).includes(q)) : this.options;
      },
      labelOf(v) {
        const o = this.options.find((x) => x.value === v);
        return o ? o.label : v;
      },
      isOn(v) {
        return this.selected.includes(v);
      },
      toggle(v) {
        this.selected = this.isOn(v) ? this.selected.filter((x) => x !== v) : [...this.selected, v];
        this.$dispatch("ms-change", { name: this.name, selected: this.selected });
      },
      clear() {
        this.selected = [];
        this.$dispatch("ms-change", { name: this.name, selected: this.selected });
      },
    }));
  });
})();
