/* E-Find — componentes Alpine do super admin. Carregado no <head> (defer) para registrar antes do Alpine iniciar. */
(function () {
  "use strict";

  document.addEventListener("alpine:init", () => {
    const Alpine = window.Alpine;

    // Abas da campanha: <div x-data="superTabs" data-tabs="dados,administradores,uso" data-initial="dados">
    // A aba fica no hash da URL (#uso) para sobreviver a redirecionamentos e poder ser compartilhada.
    Alpine.data("superTabs", () => ({
      tab: "",
      tabs: [],
      init() {
        this.tabs = (this.$el.dataset.tabs || "").split(",").filter(Boolean);
        const initial = this.$el.dataset.initial;
        this.tab = this.resolve(this.fromHash()) || this.resolve(initial) || this.tabs[0] || "";
        window.addEventListener("hashchange", () => {
          const next = this.resolve(this.fromHash());
          if (next) this.tab = next;
        });
      },
      fromHash() {
        return (window.location.hash || "").replace(/^#/, "");
      },
      resolve(name) {
        return this.tabs.includes(name) ? name : "";
      },
      select(name) {
        if (!this.resolve(name)) return;
        this.tab = name;
        try {
          window.history.replaceState(null, "", "#" + name);
        } catch (e) {
          /* ambientes que bloqueiam a History API: a aba continua funcionando sem o hash */
        }
      },
    }));

    // Exclusão definitiva: o botão só habilita quando o identificador digitado confere (o servidor valida de novo).
    //   <div x-data="deleteConfirm" data-slug="joao-silva"> ... <input x-model="typed"> <button :disabled="!ready">
    Alpine.data("deleteConfirm", () => ({
      typed: "",
      slug: "",
      init() {
        this.slug = this.$el.dataset.slug || "";
      },
      get ready() {
        return this.slug !== "" && this.typed.trim() === this.slug;
      },
    }));
  });
})();
