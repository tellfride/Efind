/* Conexões de WhatsApp: componentes Alpine do assistente (mostrar/ocultar segredo, testar conexão,
   mensagem de teste e registro automático do webhook). As chamadas são POST com CSRF; nenhum segredo trafega
   para o navegador (o servidor devolve apenas mensagens e o status). */
document.addEventListener("alpine:init", () => {
  const csrfToken = (root) => {
    const input = root.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  };

  // POST JSON com tratamento uniforme de erros (rede, sessão expirada, limite de uso)
  async function postJson(url, token, body) {
    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": token },
        body: JSON.stringify(body || {}),
      });
    } catch (e) {
      return { ok: false, status: 0, data: { message: "Sem conexão com o servidor. Verifique sua internet e tente de novo." } };
    }
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    if (res.status === 401) data.message = "Sua sessão expirou. Entre novamente para continuar.";
    else if (res.status === 403 && !data.message) data.message = data.error || "Você não tem permissão para esta ação.";
    else if (!data.message) data.message = data.error || "Não foi possível concluir a operação.";
    return { ok: res.ok && data.ok !== false, status: res.status, data };
  }

  // Campo de segredo: alterna entre texto e senha no input renderizado pelo Django
  Alpine.data("waSecretField", () => ({
    show: false,
    root: null,
    init() {
      this.root = this.$el;
    },
    toggle() {
      const input = this.root && this.root.querySelector("input");
      if (!input) return;
      this.show = !this.show;
      input.type = this.show ? "text" : "password";
    },
  }));

  // Passo 4: testar a conexão e atualizar o status exibido
  Alpine.data("waConnectionTest", () => ({
    loading: false,
    ok: false,
    message: "",
    tone: "gray",
    statusLabel: "",
    root: null,
    init() {
      this.root = this.$el;
      const d = this.root.dataset;
      this.tone = d.statusTone || "gray";
      this.statusLabel = d.statusLabel || "";
    },
    async run() {
      if (this.loading) return;
      this.loading = true;
      this.message = "";
      const { ok, data } = await postJson(this.root.dataset.url, csrfToken(this.root), {});
      this.loading = false;
      this.ok = ok;
      this.message = data.message || "";
      if (data.status_label) this.statusLabel = data.status_label;
      if (data.status_tone) this.tone = data.status_tone;
    },
  }));

  // Passo 4: mensagem de teste para um número digitado
  Alpine.data("waMessageTest", () => ({
    loading: false,
    ok: false,
    message: "",
    errors: {},
    root: null,
    init() {
      this.root = this.$el;
    },
    async send() {
      if (this.loading) return;
      const form = this.$refs.form;
      const fd = new FormData(form);
      const to = String(fd.get("to") || "").trim();
      const useTemplate = fd.get("use_template") === "on";
      this.errors = {};
      this.message = "";
      if (!to) {
        this.errors = { to: "Informe o número de destino." };
        return;
      }
      this.loading = true;
      const { ok, data } = await postJson(this.root.dataset.url, csrfToken(this.root), {
        to,
        text: String(fd.get("text") || ""),
        use_template: useTemplate,
      });
      this.loading = false;
      this.ok = ok;
      this.errors = ok ? {} : data.errors || {};
      // erros de campo já aparecem junto ao campo; a mensagem geral cobre o resto
      this.message = !ok && Object.keys(this.errors).length ? "" : data.message || "";
    },
  }));

  // Passo 3 (360dialog): registrar a URL de callback automaticamente
  Alpine.data("waRegisterWebhook", () => ({
    loading: false,
    ok: false,
    message: "",
    root: null,
    init() {
      this.root = this.$el;
    },
    async register() {
      if (this.loading) return;
      this.loading = true;
      this.message = "";
      const { ok, data } = await postJson(this.root.dataset.url, csrfToken(this.root), {});
      this.loading = false;
      this.ok = ok;
      this.message = data.message || "";
    },
  }));
});
