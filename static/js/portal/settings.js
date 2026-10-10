/* Configurações da campanha (Alpine): pré-visualização ao vivo do formulário público e processamento do logo.
 *
 * - Os campos continuam sendo inputs normais do Django; este componente apenas LÊ o DOM (readFields) a cada
 *   input/change e alimenta a pré-visualização. Sem JavaScript, as páginas e os formulários seguem funcionando
 *   (só não há pré-visualização nem envio de logo).
 * - O logo é redimensionado (máx. 512 px) e recodificado no navegador (WebP, ou PNG se o navegador não codificar WebP)
 *   até caber em 300 KB, e vai no campo oculto `logo_data` como data URL. O servidor revalida tudo (apps/portal).
 * - Configuração vem do servidor via json_script: #portal-settings-config e #portal-logo-state.
 */
(function () {
  "use strict";

  var HEX = /^#[0-9a-fA-F]{6}$/;
  var MODE_KEYS = ["email", "birth_date", "gender", "address", "electoral"];
  var DIMENSIONS = [512, 384, 256, 192, 128];
  var QUALITIES = [0.92, 0.85, 0.75, 0.6, 0.45];
  var DEFAULT_COLOR = "#4f46e5";

  function readJson(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    try {
      return JSON.parse(el.textContent) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function channel(hex, start) {
    var c = parseInt(hex.slice(start, start + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  function luminance(hex) {
    return 0.2126 * channel(hex, 1) + 0.7152 * channel(hex, 3) + 0.0722 * channel(hex, 5);
  }

  // Mesma regra do servidor (settings_rules.readable_text_color): melhor contraste WCAG entre branco e #0f172a
  function readableText(hex) {
    var lum = luminance(hex);
    var withWhite = 1.05 / (lum + 0.05);
    var withDark = (lum + 0.05) / (luminance("#0f172a") + 0.05);
    return withWhite >= withDark ? "#ffffff" : "#0f172a";
  }

  function fitWithin(w, h, max) {
    var scale = Math.min(1, max / Math.max(w, h));
    return { width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale)) };
  }

  function dataUrlBytes(dataUrl) {
    var payload = dataUrl.slice(dataUrl.indexOf(",") + 1);
    var padding = payload.endsWith("==") ? 2 : payload.endsWith("=") ? 1 : 0;
    return Math.floor((payload.length * 3) / 4) - padding;
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1).replace(".", ",") + " MB";
  }

  function loadImage(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("Não foi possível ler a imagem. Verifique se o arquivo não está corrompido."));
      };
      img.src = url;
    });
  }

  async function processLogoFile(file, limits) {
    if (limits.accepted.indexOf(file.type) === -1) throw new Error("Formato não suportado. Use PNG, JPEG ou WebP.");
    if (file.size > limits.maxSourceBytes) {
      throw new Error("Arquivo muito grande (" + formatBytes(file.size) + "). Escolha uma imagem de até " + Math.round(limits.maxSourceBytes / (1024 * 1024)) + " MB.");
    }
    var img = await loadImage(file);
    var srcW = img.naturalWidth;
    var srcH = img.naturalHeight;
    if (!srcW || !srcH) throw new Error("Imagem inválida.");

    var canvas = document.createElement("canvas");
    var ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Seu navegador não permite processar imagens.");

    for (var d = 0; d < DIMENSIONS.length; d++) {
      var max = Math.min(DIMENSIONS[d], limits.maxDimension);
      var size = fitWithin(srcW, srcH, max);
      canvas.width = size.width;
      canvas.height = size.height;
      ctx.clearRect(0, 0, size.width, size.height);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(img, 0, 0, size.width, size.height);

      for (var q = 0; q < QUALITIES.length; q++) {
        var dataUrl = canvas.toDataURL("image/webp", QUALITIES[q]);
        var format = "WebP";
        if (dataUrl.indexOf("data:image/webp") !== 0) {
          // Navegadores sem codificador WebP devolvem PNG
          dataUrl = canvas.toDataURL("image/png");
          format = "PNG";
        }
        var bytes = dataUrlBytes(dataUrl);
        if (bytes <= limits.maxBytes) {
          return { dataUrl: dataUrl, width: size.width, height: size.height, bytes: bytes, format: format };
        }
        if (format === "PNG") break; // qualidade não vale para PNG: tenta uma dimensão menor
      }
    }
    throw new Error("Não foi possível reduzir a imagem para até " + Math.round(limits.maxBytes / 1024) + " KB. Tente um arquivo mais simples.");
  }

  function toast(message, level) {
    if (window.EFind && typeof window.EFind.toast === "function") window.EFind.toast(message, level);
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("portalSettings", function () {
      return {
        cfg: readJson("portal-settings-config", { logo: { maxBytes: 307200, maxDimension: 512, maxSourceBytes: 15728640, accepted: [] } }),

        // Campos lidos do DOM
        ballotName: "",
        ballotNumber: "",
        party: "",
        color: DEFAULT_COLOR,
        formTitle: "",
        formMessage: "",
        consentText: "",
        modes: { email: "optional", birth_date: "optional", gender: "optional", address: "required", electoral: "optional" },

        // Logo
        logoAction: "keep",
        logoData: "",
        logoSaved: "",
        logoInfo: "",
        logoBusy: false,
        logoError: "",
        saving: "",

        init: function () {
          var state = readJson("portal-logo-state", { saved: "", action: "keep", echo: "" });
          this.logoSaved = state.saved || "";
          if (state.action === "replace" && state.echo) {
            this.logoAction = "replace";
            this.logoData = state.echo;
            this.logoInfo = "Novo logo · " + formatBytes(dataUrlBytes(state.echo));
          } else if (state.action === "remove") {
            this.logoAction = "remove";
          }
          this.readFields();
        },

        // ------------------------------------------------------------------ leitura do DOM
        readFields: function () {
          var val = function (id) {
            var el = document.getElementById(id);
            return el ? el.value : "";
          };
          this.ballotName = val("id_ballot_name").trim();
          this.ballotNumber = val("id_ballot_number").trim();
          this.party = val("id_party").trim();
          this.formTitle = val("id_form_title").trim();
          this.formMessage = val("id_form_message");
          this.consentText = val("id_consent_text");
          var text = val("id_primary_color").trim();
          if (HEX.test(text)) {
            this.color = text.toLowerCase();
            if (this.$refs.picker && this.$refs.picker.value !== this.color) this.$refs.picker.value = this.color;
          }
          for (var i = 0; i < MODE_KEYS.length; i++) {
            var checked = document.querySelector('input[name="config_' + MODE_KEYS[i] + '"]:checked');
            if (checked) this.modes[MODE_KEYS[i]] = checked.value;
          }
        },

        onPicker: function (event) {
          var input = document.getElementById("id_primary_color");
          if (input) input.value = event.target.value.toLowerCase();
          this.readFields();
        },

        onSubmit: function (event, section) {
          if (this.logoBusy) {
            event.preventDefault();
            return;
          }
          this.saving = section;
        },

        restoreConsent: function () {
          var el = document.getElementById("id_consent_text");
          if (el) el.value = "";
          this.readFields();
        },

        // ------------------------------------------------------------------ derivados (pré-visualização)
        get textColor() {
          return readableText(this.color);
        },
        get displayName() {
          return this.ballotName || "Nome de urna";
        },
        get initial() {
          return this.ballotNumber.slice(0, 2) || this.displayName.charAt(0).toUpperCase();
        },
        get subtitle() {
          return [this.ballotNumber, this.party].filter(Boolean).join(" · ");
        },
        get previewTitle() {
          return this.formTitle || "Faça parte da campanha de " + this.displayName;
        },
        get consentPreview() {
          var name = this.displayName;
          var base = this.consentText.trim() || (this.cfg.defaultConsent || "");
          // Mesma regra do servidor (render_template): {{candidato}} vira o nome de urna; outras variáveis somem
          return base.replace(/\{\{\s*([a-zA-Z_]+)\s*\}\}/g, function (_m, key) {
            return key.toLowerCase() === "candidato" ? name : "";
          });
        },
        get optInText() {
          return this.cfg.optInText || "";
        },
        get logoUrl() {
          if (this.logoAction === "replace") return this.logoData;
          if (this.logoAction === "remove") return "";
          return this.logoSaved;
        },
        get logoStatus() {
          if (this.logoAction === "remove") return "O logo será removido ao salvar.";
          if (this.logoAction === "replace") return this.logoInfo || "Novo logo pronto. Salve para aplicar.";
          return this.logoSaved ? "Logo atual · " + formatBytes(dataUrlBytes(this.logoSaved)) : "Nenhum logo enviado.";
        },
        shown: function (key) {
          return this.modes[key] !== "hidden";
        },
        required: function (key) {
          return this.modes[key] === "required";
        },

        // ------------------------------------------------------------------ logo
        pickLogo: async function (event) {
          var input = event.target;
          var file = input.files && input.files[0];
          if (!file) return;
          this.logoError = "";
          this.logoBusy = true;
          try {
            var result = await processLogoFile(file, this.cfg.logo);
            this.logoData = result.dataUrl;
            this.logoAction = "replace";
            this.logoInfo = "Novo logo · " + result.format + " · " + result.width + "×" + result.height + " px · " + formatBytes(result.bytes);
            toast("Logo pronto. Salve a identidade para aplicar.", "success");
          } catch (err) {
            this.logoError = err && err.message ? err.message : "Não foi possível processar a imagem.";
          } finally {
            this.logoBusy = false;
            input.value = "";
          }
        },
        removeLogo: function () {
          if (this.logoAction === "replace" && !this.logoSaved) {
            this.undoLogo();
            return;
          }
          if (window.confirm("Remover o logo da campanha? Ele deixará de aparecer no formulário e no painel depois de salvar.")) {
            this.logoAction = "remove";
            this.logoData = "";
            this.logoError = "";
          }
        },
        undoLogo: function () {
          this.logoAction = "keep";
          this.logoData = "";
          this.logoInfo = "";
          this.logoError = "";
        },
      };
    });
  });
})();
