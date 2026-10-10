/* E-Find · lista de eleitores: mantém a ordenação escolhida ao aplicar os filtros. */
(function () {
  "use strict";
  document.addEventListener("submit", (e) => {
    const wrap = e.target.closest && e.target.closest("[data-voter-filters]");
    if (!wrap || !wrap.dataset.sort || wrap.dataset.sort === "recentes") return;
    const form = e.target;
    if (!form.querySelector('input[name="ordem"]')) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "ordem";
      input.value = wrap.dataset.sort;
      form.appendChild(input);
    }
  });
})();
