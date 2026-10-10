/* Permissões: matriz por papel e exceções por usuário (Alpine).
   Regras de tela (o servidor renormaliza sempre):
   - desligar "Ver" limpa a linha do módulo; ligar qualquer ação liga "Ver";
   - exceção: "Negar" em "Ver" zera as demais; "Permitir" numa ação exige "Ver" efetivo. */
document.addEventListener("alpine:init", () => {
  const readJson = (id) => {
    const el = document.getElementById(id);
    try {
      return el ? JSON.parse(el.textContent) : {};
    } catch (e) {
      return {};
    }
  };
  const clone = (obj) => JSON.parse(JSON.stringify(obj || {}));

  // Matriz de um papel: checkboxes name="perm__<módulo>__<ação>"
  Alpine.data("permissionMatrix", (slug) => {
    const cfg = readJson("perm-config");
    const m = clone((cfg.roles || {})[slug]);
    return {
      m,
      supported: cfg.supported || {},
      initial: JSON.stringify(m),

      set(module, action, value) {
        const row = this.m[module];
        if (!row) return;
        row[action] = value;
        if (action === "view" && !value) {
          for (const a of Object.keys(row)) row[a] = false;
        } else if (value && action !== "view") {
          row.view = true;
        }
      },

      get enabled() {
        let n = 0;
        for (const module of Object.keys(this.supported)) {
          for (const a of this.supported[module]) if (this.m[module] && this.m[module][a]) n++;
        }
        return n;
      },

      get dirty() {
        return JSON.stringify(this.m) !== this.initial;
      },
    };
  });

  // Exceções de um usuário: selects name="ov__<módulo>__<ação>" (inherit | allow | deny)
  Alpine.data("overrideMatrix", () => {
    const cfg = readJson("override-config");
    const v = clone(cfg.values);
    return {
      v,
      inherited: cfg.inherited || {},
      supported: cfg.supported || {},
      initial: JSON.stringify(v),

      // valor da célula considerando a exceção (sem olhar "Ver")
      raw(module, action) {
        const value = this.v[module][action];
        if (value === "allow") return true;
        if (value === "deny") return false;
        return !!this.inherited[module][action];
      },

      // valor final: sem "Ver" nenhuma ação vale
      final(module, action) {
        return action === "view" ? this.raw(module, "view") : this.raw(module, "view") && this.raw(module, action);
      },

      onChange(module, action) {
        const row = this.v[module];
        if (action === "view" && row.view === "deny") {
          for (const a of this.supported[module]) if (a !== "view") row[a] = "inherit";
        } else if (action !== "view" && row[action] === "allow" && !this.raw(module, "view")) {
          row.view = "allow";
        }
      },

      get changed() {
        let n = 0;
        for (const module of Object.keys(this.supported)) {
          for (const a of this.supported[module]) if (this.v[module] && this.v[module][a] !== "inherit") n++;
        }
        return n;
      },

      get dirty() {
        return JSON.stringify(this.v) !== this.initial;
      },
    };
  });
});
