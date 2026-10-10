/* E-Find — Dashboards: página de visualização (/painel/ e /painel/dashboards/<id>/).
 * Componente Alpine `dashboardView`: desenha a grade, atualiza os dados (botão e a cada N segundos) e mostra o estado. */
(function () {
  "use strict";

  document.addEventListener("alpine:init", () => {
    window.Alpine.data("dashboardView", () => {
      // Objetos pesados ficam fora da reatividade do Alpine
      let board = null;
      let timer = null;

      return {
        busy: false,
        updated: "",
        failed: "",

        init() {
          const node = document.getElementById("dash-config");
          const grid = this.$root.querySelector("[data-dash-grid]");
          if (!node || !grid || !window.EFindDash) return;
          const cfg = JSON.parse(node.textContent);
          board = new window.EFindDash.Board({
            grid,
            config: cfg,
            editable: false,
            hooks: {
              busy: (value) => {
                this.busy = value;
              },
              loaded: () => {
                this.failed = "";
                this.updated = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
              },
              refreshFailed: (message) => {
                this.failed = message;
              },
            },
          });
          board.render();
          board.load();
          if (cfg.autoRefresh > 0) {
            timer = window.setInterval(() => {
              if (document.visibilityState === "visible" && !this.busy) board.load(null, { silent: true });
            }, cfg.autoRefresh * 1000);
          }
        },

        refresh() {
          if (board && !this.busy) board.load(null, { silent: true });
        },

        destroy() {
          if (timer) window.clearInterval(timer);
          if (board) board.destroy();
        },
      };
    });
  });
})();
