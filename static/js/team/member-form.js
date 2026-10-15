/* Equipe: formulário de membro (cadastro e edição).
   Componente Alpine `memberForm`: mostra/oculta o responsável conforme o papel e lista só os superiores válidos.
   É conveniência de tela — o servidor revalida papel e responsável em toda requisição. */
document.addEventListener("alpine:init", () => {
  Alpine.data("memberForm", (cfg) => ({
    role: cfg.role || "CABO",
    parent: cfg.parent || "",
    candidates: cfg.candidates || [],
    hasCoordinators: !!cfg.hasCoordinators,
    originalRole: cfg.originalRole || "",
    originalParent: cfg.originalParent || "",
    actorId: cfg.actorId || "",

    init() {
      this.$nextTick(() => this.syncParent());
    },

    get needsParent() {
      return this.role === "COORDENADOR" || this.role === "CABO";
    },

    get parentLabel() {
      return this.role === "COORDENADOR" ? "Administrador responsável" : "Coordenador responsável";
    },

    get parentHint() {
      if (this.role === "COORDENADOR") return "O coordenador fica abaixo de um administrador.";
      if (this.parentOptions.length && this.parentOptions[0].role === "ADMIN") {
        return "A campanha não tem coordenadores ativos: o cabo fica abaixo do administrador.";
      }
      return "O cabo eleitoral fica abaixo de um coordenador e aparece na rede dele.";
    },

    get roleHint() {
      if (this.role === "ADMIN") return "Acesso total à campanha. Só administradores criam outros administradores.";
      if (this.role === "COORDENADOR") return "Vê a própria rede: ele e os cabos que estão abaixo dele.";
      return "Vê apenas os apoiadores que ele mesmo cadastrar.";
    },

    // Superiores válidos para o papel escolhido (mesma regra do servidor)
    get parentOptions() {
      const keepOriginal = this.role === this.originalRole;
      const usable = this.candidates.filter((c) => c.active || (keepOriginal && c.id === this.originalParent));
      if (this.role === "COORDENADOR") return usable.filter((c) => c.role === "ADMIN");
      if (this.role === "CABO") {
        const coordinators = usable.filter((c) => c.role === "COORDENADOR");
        if (coordinators.length || this.hasCoordinators) return coordinators;
        return usable.filter((c) => c.role === "ADMIN");
      }
      return [];
    },

    syncParent() {
      if (!this.needsParent) return;
      const options = this.parentOptions;
      if (options.some((c) => c.id === this.parent)) return;
      if (this.role === "COORDENADOR") {
        const me = options.find((c) => c.id === this.actorId);
        this.parent = me ? me.id : options.length === 1 ? options[0].id : "";
      } else {
        this.parent = options.length === 1 ? options[0].id : "";
      }
    },

    onRoleChange() {
      this.syncParent();
    },
  }));
});
