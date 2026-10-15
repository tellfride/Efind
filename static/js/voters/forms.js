/* E-Find · formulários de apoiador: máscara de data (dd/mm/aaaa) e proteção contra envio duplo. */
(function () {
  "use strict";

  function maskDate(value) {
    const d = value.replace(/\D/g, "").slice(0, 8);
    if (d.length <= 2) return d;
    if (d.length <= 4) return d.slice(0, 2) + "/" + d.slice(2);
    return d.slice(0, 2) + "/" + d.slice(2, 4) + "/" + d.slice(4);
  }

  document.addEventListener("input", (e) => {
    const el = e.target;
    if (el instanceof HTMLInputElement && el.dataset.mask === "date") el.value = maskDate(el.value);
  });

  // Depois de preencher o endereço pelo CEP, leva o foco ao número (o único dado que falta)
  document.addEventListener("cep:found", (e) => {
    const form = e.target && e.target.closest ? e.target.closest("form") : null;
    const number = form && form.querySelector("#id_number");
    if (number && !number.value) number.focus();
  });

  // Desabilita o botão de envio após o primeiro clique (evita cadastro duplicado em conexões lentas)
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented) return;
    const button = form.querySelector("button[data-submit]");
    if (!button) return;
    setTimeout(() => {
      button.disabled = true;
      if (button.dataset.submitLabel) button.textContent = button.dataset.submitLabel;
    }, 0);
  });

  // Ao voltar pelo histórico (bfcache) o botão deve voltar a funcionar
  window.addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    document.querySelectorAll("button[data-submit]").forEach((b) => (b.disabled = false));
  });
})();
