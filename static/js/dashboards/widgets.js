/* E-Find — Dashboards: formatação e desenho dos widgets (Chart.js + DOM).
 *
 * Cada renderizador recebe (body, data, widget, ctx) e preenche `body` com nós DOM.
 * Segurança: NENHUM texto vindo do servidor passa por innerHTML; tudo entra via textContent/createTextNode
 * (helper `el`). Os ícones vêm de <template> gerados pelo servidor a partir dos arquivos do projeto.
 * Classes do Tailwind sempre escritas por inteiro (o CSS é gerado escaneando este arquivo).
 */
(function () {
  "use strict";

  const D = (window.EFindDash = window.EFindDash || {});

  // ------------------------------------------------------------------ Formatação (pt-BR)
  const nf = new Intl.NumberFormat("pt-BR");
  const nf1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 1 });
  const fmt = (n) => nf.format(Number(n) || 0);
  const fmtPct = (n) => (n === null || n === undefined || Number.isNaN(Number(n)) ? "—" : nf1.format(Number(n)) + "%");
  const rtf = typeof Intl.RelativeTimeFormat === "function" ? new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" }) : null;
  const WEEKDAYS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

  const PERIOD_LABELS = { 7: "Últimos 7 dias", 30: "Últimos 30 dias", 90: "Últimos 90 dias", 365: "Últimos 12 meses" };
  const PERIOD_SHORT = { 7: "nos últimos 7 dias", 30: "nos últimos 30 dias", 90: "nos últimos 90 dias", 365: "nos últimos 12 meses" };

  function periodLabel(days) {
    return PERIOD_LABELS[days] || PERIOD_LABELS[30];
  }

  function timeAgo(iso) {
    const date = new Date(iso);
    if (!iso || Number.isNaN(date.getTime())) return "—";
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const abs = Math.abs(seconds);
    if (abs < 60) return "agora";
    if (!rtf) return date.toLocaleDateString("pt-BR");
    if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
    if (abs < 7 * 86400) return rtf.format(Math.round(seconds / 86400), "day");
    return date.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
  }

  function fullDateTime(iso) {
    const date = new Date(iso);
    if (!iso || Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" });
  }

  function shortDate(key) {
    const [, m, d] = String(key).split("-");
    return d + "/" + m;
  }

  function longDate(key) {
    const [y, m, d] = String(key).split("-").map(Number);
    const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
    return weekday + ", " + String(d).padStart(2, "0") + "/" + String(m).padStart(2, "0") + "/" + y;
  }

  function percentOf(part, whole) {
    return whole > 0 ? (part / whole) * 100 : 0;
  }

  function initials(name) {
    const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  }

  // ------------------------------------------------------------------ DOM seguro
  function append(node, content) {
    if (content === null || content === undefined || content === false) return node;
    if (Array.isArray(content)) content.forEach((c) => append(node, c));
    else if (typeof content === "object" && content.nodeType) node.appendChild(content);
    else node.appendChild(document.createTextNode(String(content)));
    return node;
  }

  function el(tag, cls, content) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    append(node, content);
    return node;
  }

  const iconCache = {};
  function iconNode(name, cls) {
    let proto = iconCache[name];
    if (proto === undefined) {
      const tpl = Array.from(document.querySelectorAll("#dash-icons template")).find((t) => t.dataset.icon === name);
      proto = tpl && tpl.content && tpl.content.firstElementChild ? tpl.content.firstElementChild : null;
      iconCache[name] = proto;
    }
    const svg = proto
      ? proto.cloneNode(true)
      : document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", cls || "size-4");
    svg.setAttribute("aria-hidden", "true");
    return svg;
  }

  function iconHtml(name, cls) {
    return iconNode(name, cls).outerHTML; // markup gerado do arquivo do projeto; o nome vem do catálogo do servidor
  }

  function setWidth(node, pct) {
    node.style.width = Math.max(0, Math.min(100, Number(pct) || 0)).toFixed(1) + "%";
  }

  function progressBar(pct, tone) {
    const wrap = el("div", "progress");
    wrap.setAttribute("role", "progressbar");
    wrap.setAttribute("aria-valuemin", "0");
    wrap.setAttribute("aria-valuemax", "100");
    wrap.setAttribute("aria-valuenow", String(Math.round(Math.max(0, Math.min(100, pct || 0)))));
    const cls = { green: "progress-bar progress-green", yellow: "progress-bar progress-yellow", red: "progress-bar progress-red" }[tone] || "progress-bar progress-brand";
    const bar = el("div", cls);
    setWidth(bar, pct);
    wrap.append(bar);
    return wrap;
  }

  function goalTone(pct) {
    if (pct >= 100) return "green";
    if (pct >= 50) return "brand";
    return "yellow";
  }

  // ------------------------------------------------------------------ Estados
  function skeleton(type) {
    const kpi = /^kpi_/.test(type);
    const wrap = el("div", "space-y-3");
    wrap.setAttribute("aria-busy", "true");
    wrap.setAttribute("aria-label", "Carregando");
    if (kpi) {
      wrap.append(el("div", "skeleton h-9 w-28"), el("div", "skeleton h-3 w-40 max-w-full"), el("div", "skeleton h-2 w-full"));
    } else {
      wrap.append(
        el("div", "skeleton h-5 w-1/3"),
        el("div", "skeleton h-28 w-full"),
        el("div", "skeleton h-4 w-2/3"),
        el("div", "skeleton h-4 w-1/2"),
      );
    }
    return wrap;
  }

  function emptyBlock(iconName, title, text) {
    return el("div", "flex flex-col items-center justify-center px-2 py-6 text-center", [
      el("div", "mb-3 flex size-10 items-center justify-center rounded-full bg-slate-100 text-slate-500", iconNode(iconName, "size-5")),
      el("p", "text-sm font-medium text-slate-700", title),
      text ? el("p", "mt-1 max-w-xs text-xs text-slate-500", text) : null,
    ]);
  }

  function lockedBlock(text) {
    return el("div", "flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600", [
      iconNode("lock", "mt-0.5 size-4 shrink-0 text-slate-400"),
      el("p", "", text),
    ]);
  }

  function errorBlock(message, onRetry) {
    const box = el("div", "flex flex-col items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900");
    box.setAttribute("role", "alert");
    box.append(
      el("div", "flex items-start gap-2", [iconNode("circle-alert", "mt-0.5 size-4 shrink-0"), el("p", "", message || "Não foi possível carregar este widget.")]),
    );
    if (onRetry) {
      const btn = el("button", "btn btn-outline btn-sm", [iconNode("refresh-cw"), "Tentar novamente"]);
      btn.type = "button";
      btn.addEventListener("click", onRetry);
      box.append(btn);
    }
    return box;
  }

  function chip(text, cls) {
    return el("span", cls || "chip", text);
  }

  // ------------------------------------------------------------------ Gráficos (Chart.js)
  const PALETTE = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"];
  const UNKNOWN_COLOR = "#cbd5e1";
  const SUPPORT_COLORS = { APOIADOR: "#10b981", SIMPATIZANTE: "#0ea5e9", INDECISO: "#f59e0b", OPOSITOR: "#ef4444" };
  let chartReady = false;

  function chartAvailable() {
    if (typeof window.Chart !== "function") return false;
    if (!chartReady) {
      const Chart = window.Chart;
      Chart.defaults.font.family = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";
      Chart.defaults.font.size = 12;
      Chart.defaults.color = "#64748b";
      if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) Chart.defaults.animation = false;
      chartReady = true;
    }
    return true;
  }

  function canvasIn(box, label) {
    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", label);
    box.append(canvas);
    return canvas;
  }

  const TOOLTIP = { backgroundColor: "#0f172a", padding: 10, cornerRadius: 8, displayColors: false };

  // ------------------------------------------------------------------ Peças reutilizáveis
  const ROLES = {
    ADMIN: ["Administrador", "badge badge-purple"],
    COORDENADOR: ["Coordenador", "badge badge-blue"],
    CABO: ["Cabo eleitoral", "badge badge-gray"],
  };
  function roleLabel(role) {
    return (ROLES[role] || [role])[0];
  }
  function roleBadge(role) {
    const [label, cls] = ROLES[role] || [role, "badge badge-gray"];
    return el("span", cls, label);
  }

  const MEDALS = [
    "bg-amber-100 text-amber-600 ring-1 ring-amber-300",
    "bg-slate-100 text-slate-500 ring-1 ring-slate-300",
    "bg-orange-100 text-orange-700 ring-1 ring-orange-300",
  ];
  // `scored`: tem cadastros no período. Quem não cadastrou nada aparece com "–" (a ordem entre eles é só alfabética).
  function rankBadge(position, scored) {
    const base = "flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold tabular-nums";
    if (!scored) return el("span", base + " bg-slate-50 text-slate-300", ["–", el("span", "sr-only", "Sem cadastros no período")]);
    if (position <= 3) {
      const node = el("span", base + " " + MEDALS[position - 1], [iconNode("medal", "size-4"), el("span", "sr-only", position + "º lugar")]);
      node.title = position + "º lugar";
      return node;
    }
    return el("span", base + " bg-slate-50 text-slate-600", [String(position), el("span", "sr-only", "º lugar")]);
  }

  function trendPill(deltaPct, trend, suffix) {
    const tones = {
      up: ["bg-emerald-50 text-emerald-700", "trending-up"],
      down: ["bg-red-50 text-red-700", "trending-down"],
      flat: ["bg-slate-100 text-slate-600", "minus"],
    };
    const [tone, name] = tones[trend] || tones.flat;
    let text;
    if (deltaPct === null || deltaPct === undefined) text = trend === "up" ? "novo" : "sem variação";
    else text = (deltaPct > 0 ? "+" : deltaPct < 0 ? "−" : "") + fmtPct(Math.abs(deltaPct));
    return el("span", "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium " + tone, [
      iconNode(name, "size-3.5"),
      text + (suffix ? " " + suffix : ""),
    ]);
  }

  function bigValue(value, hint, extra) {
    return el("div", "space-y-1.5", [
      el("p", "text-3xl font-bold tracking-tight text-slate-900 tabular-nums", value),
      hint ? el("p", "text-xs text-slate-500", hint) : null,
      extra || null,
    ]);
  }

  function statTile(label, value, sub, valueCls) {
    return el("div", "rounded-lg border border-slate-200 bg-slate-50/60 p-3", [
      el("p", "text-xs font-medium text-slate-500", label),
      el("p", "mt-1 text-xl font-bold tabular-nums " + (valueCls || "text-slate-900"), value),
      sub ? el("p", "mt-0.5 text-xs text-slate-500", sub) : null,
    ]);
  }

  function safePath(url) {
    return typeof url === "string" && /^\/painel\/[A-Za-z0-9/_-]*$/.test(url) ? url : "";
  }

  // ------------------------------------------------------------------ Renderizadores
  const R = {};

  // --- Indicadores
  R.kpi_total = (body, d) => {
    body.append(bigValue(fmt(d.total), d.last7 > 0 ? "+" + fmt(d.last7) + " nos últimos 7 dias" : "Nenhum cadastro nos últimos 7 dias"));
  };

  R.kpi_today = (body, d) => {
    const delta = d.yesterday > 0 ? ((d.today - d.yesterday) / d.yesterday) * 100 : null;
    const trend = d.today > d.yesterday ? "up" : d.today < d.yesterday ? "down" : "flat";
    body.append(bigValue(fmt(d.today), "Ontem: " + fmt(d.yesterday), trendPill(delta, trend, "vs. ontem")));
  };

  R.kpi_period = (body, d) => {
    const c = d.comparison || { current: 0, previous: 0, delta_pct: null, trend: "flat" };
    body.append(
      bigValue(fmt(c.current), periodLabel(d.period) + " · anterior: " + fmt(c.previous), trendPill(c.delta_pct, c.trend, "vs. período anterior")),
    );
  };

  R.kpi_goal = (body, d) => {
    if (!d.goal) {
      body.append(
        bigValue(fmt(d.total), "Meta não definida", null),
        el("p", "mt-2 text-xs text-slate-500", d.source === "campaign" ? "Defina a meta de cadastros da campanha nas configurações." : "Peça ao administrador para definir as metas individuais da equipe."),
      );
      return;
    }
    const pct = d.pct || 0;
    body.append(
      bigValue(fmtPct(pct), fmt(d.total) + " de " + fmt(d.goal) + " apoiadores", null),
      el("div", "mt-2", progressBar(pct, goalTone(pct))),
      el("p", "mt-2 text-xs text-slate-500", d.source === "campaign" ? "Meta da campanha" : "Soma das metas de " + fmt(d.members_with_goal) + " membro(s) da sua equipe"),
    );
  };

  R.kpi_messageable = (body, d) => {
    const hint = d.total > 0 ? fmtPct(d.pct) + " dos " + fmt(d.total) + " apoiadores" : "Nenhum apoiador cadastrado";
    body.append(bigValue(fmt(d.messageable), hint, null), el("div", "mt-2", progressBar(d.pct || 0, "green")));
  };

  R.kpi_team = (body, d) => {
    body.append(
      bigValue(fmt(d.active), d.active === 1 ? "membro ativo" : "membros ativos", null),
      el("p", "mt-2 text-sm text-slate-700", [
        el("span", "font-semibold tabular-nums", fmt(d.contributing)),
        " cadastraram " + (PERIOD_SHORT[d.period] || PERIOD_SHORT[30]),
      ]),
      el("div", "mt-2", progressBar(d.pct || 0, "brand")),
    );
  };

  // --- Cadastros por cabo eleitoral (requisito central)
  function lastCell(iso) {
    const span = el("span", "text-slate-600", iso ? timeAgo(iso) : "—");
    if (iso) span.title = fullDateTime(iso);
    return span;
  }

  function goalCell(row) {
    if (!row.goal) return el("span", "text-slate-400", "—");
    const pct = row.goal_pct || 0;
    return el("div", "w-28", [
      el("div", "mb-1 flex items-center justify-between text-xs", [
        el("span", "font-semibold tabular-nums text-slate-700", fmtPct(pct)),
        el("span", "tabular-nums text-slate-400", fmt(row.total) + "/" + fmt(row.goal)),
      ]),
      progressBar(pct, goalTone(pct)),
    ]);
  }

  function nameBlock(row, sub) {
    return el("div", "min-w-0", [
      el("p", "truncate font-medium text-slate-900", row.name),
      el("div", "mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500", sub),
    ]);
  }

  function memberSub(row) {
    return [
      roleBadge(row.role),
      row.coordinator_name ? el("span", "truncate", "Coord.: " + row.coordinator_name) : null,
      row.active ? null : el("span", "badge badge-red", "inativo"),
    ];
  }

  function rankingMobileList(rows, maxPeriod) {
    const ul = el("ul", "divide-y divide-slate-100 @xl:hidden");
    rows.forEach((row, i) => {
      const meta = [
        "Total: " + fmt(row.total),
        row.goal ? "Meta: " + fmtPct(row.goal_pct) : null,
        "Último: " + (row.last_at ? timeAgo(row.last_at) : "—"),
      ].filter(Boolean);
      ul.append(
        el("li", "py-3", [
          el("div", "flex items-center gap-3", [
            rankBadge(i + 1, row.in_period > 0),
            el("div", "min-w-0 flex-1", nameBlock(row, memberSub(row))),
            el("div", "text-right", [
              el("p", "text-xl leading-none font-bold tabular-nums " + (row.in_period > 0 ? "text-slate-900" : "text-slate-400"), fmt(row.in_period)),
              el("p", "mt-1 text-[11px] text-slate-500", "no período"),
            ]),
          ]),
          el("div", "mt-2.5", progressBar(percentOf(row.in_period, maxPeriod), "brand")),
          el("p", "mt-1.5 text-xs text-slate-500", meta.join(" · ")),
        ]),
      );
    });
    return ul;
  }

  function rankingTable(rows, maxPeriod) {
    const wrap = el("div", "table-wrap hidden @xl:block");
    const table = el("table", "table");
    const head = el("tr", "", [
      el("th", "w-12", "#"),
      el("th", "", "Cabo eleitoral"),
      el("th", "min-w-48", "Cadastros no período"),
      el("th", "text-right", "Total"),
      el("th", "", "Meta"),
      el("th", "", "Último cadastro"),
    ]);
    table.append(el("thead", "", head));
    const tbody = el("tbody");
    rows.forEach((row, i) => {
      tbody.append(
        el("tr", "", [
          el("td", "", rankBadge(i + 1, row.in_period > 0)),
          el("td", "max-w-64", nameBlock(row, memberSub(row))),
          el("td", "", [
            el("div", "flex items-center gap-3", [
              el("div", "min-w-24 flex-1", progressBar(percentOf(row.in_period, maxPeriod), "brand")),
              el("span", "w-10 text-right text-base font-bold tabular-nums " + (row.in_period > 0 ? "text-slate-900" : "text-slate-400"), fmt(row.in_period)),
            ]),
          ]),
          el("td", "text-right tabular-nums", fmt(row.total)),
          el("td", "", goalCell(row)),
          el("td", "whitespace-nowrap", lastCell(row.last_at)),
        ]),
      );
    });
    table.append(tbody);
    wrap.append(table);
    return wrap;
  }

  R.ranking_members = (body, d) => {
    const rows = d.rows || [];
    if (!rows.length) {
      body.append(emptyBlock("trophy", "Nenhum cadastro ainda", "Quando a equipe começar a cadastrar apoiadores, o ranking aparece aqui."));
      return;
    }
    const limit = d.limit || 10;
    const maxPeriod = Math.max(1, ...rows.map((r) => r.in_period));
    let expanded = false;

    body.append(
      el("div", "mb-3 flex flex-wrap gap-2", [
        chip(fmt(d.period_total) + " cadastro(s) · " + periodLabel(d.period).toLowerCase()),
        chip(fmt(d.contributing) + " de " + fmt(d.active_members) + " membro(s) cadastraram"),
        chip(fmt(d.total) + " no total"),
      ]),
    );
    const list = el("div");
    const footer = el("div", "mt-3 flex justify-center");
    body.append(list, footer);

    function paint() {
      const shown = expanded ? rows : rows.slice(0, limit);
      list.replaceChildren(rankingMobileList(shown, maxPeriod), rankingTable(shown, maxPeriod));
      footer.replaceChildren();
      if (rows.length > limit) {
        const btn = el("button", "btn btn-outline btn-sm", expanded ? "Mostrar menos" : "Ver todos (" + fmt(rows.length) + ")");
        btn.type = "button";
        btn.setAttribute("aria-expanded", expanded ? "true" : "false");
        btn.addEventListener("click", () => {
          expanded = !expanded;
          paint();
        });
        footer.append(btn);
      }
    }
    paint();
  };

  R.ranking_coordinators = (body, d) => {
    if (d.applicable === false) {
      body.append(emptyBlock("layers", "Disponível para coordenadores e administradores", "Este ranking agrupa os cabos eleitorais de cada coordenador."));
      return;
    }
    const all = d.rows || [];
    if (!all.length) {
      body.append(emptyBlock("layers", "Nenhum coordenador na equipe", "Cadastre coordenadores em Equipe para acompanhar o desempenho de cada rede."));
      return;
    }
    const limit = d.limit || 10;
    const maxPeriod = Math.max(1, ...all.map((r) => r.in_period));
    let expanded = false;
    const list = el("div");
    const footer = el("div", "mt-3 flex justify-center");
    body.append(list, footer);

    const sub = (r) => [
      el("span", "", fmt(r.cabos) + (r.cabos === 1 ? " cabo" : " cabos")),
      r.own > 0 ? el("span", "", "próprios: " + fmt(r.own)) : null,
      r.active ? null : el("span", "badge badge-red", "inativo"),
    ];

    function paint() {
      const rows = expanded ? all : all.slice(0, limit);
      const ul = el("ul", "divide-y divide-slate-100 @xl:hidden");
      rows.forEach((r, i) => {
        ul.append(
          el("li", "py-3", [
            el("div", "flex items-center gap-3", [
              rankBadge(i + 1, r.in_period > 0),
              el("div", "min-w-0 flex-1", nameBlock(r, sub(r))),
              el("div", "text-right", [
                el("p", "text-xl leading-none font-bold tabular-nums " + (r.in_period > 0 ? "text-slate-900" : "text-slate-400"), fmt(r.in_period)),
                el("p", "mt-1 text-[11px] text-slate-500", "no período"),
              ]),
            ]),
            el("div", "mt-2.5", progressBar(percentOf(r.in_period, maxPeriod), "brand")),
            el("p", "mt-1.5 text-xs text-slate-500", ["Total da rede: " + fmt(r.total), r.goal ? "Meta: " + fmtPct(r.goal_pct) : null].filter(Boolean).join(" · ")),
          ]),
        );
      });
      const wrap = el("div", "table-wrap hidden @xl:block");
      const table = el("table", "table");
      table.append(
        el("thead", "", el("tr", "", [
          el("th", "w-12", "#"),
          el("th", "", "Coordenador"),
          el("th", "min-w-48", "Cadastros no período"),
          el("th", "text-right", "Total da rede"),
          el("th", "", "Meta"),
        ])),
      );
      const tbody = el("tbody");
      rows.forEach((r, i) => {
        tbody.append(
          el("tr", "", [
            el("td", "", rankBadge(i + 1, r.in_period > 0)),
            el("td", "max-w-64", nameBlock(r, sub(r))),
            el("td", "", el("div", "flex items-center gap-3", [
              el("div", "min-w-24 flex-1", progressBar(percentOf(r.in_period, maxPeriod), "brand")),
              el("span", "w-10 text-right text-base font-bold tabular-nums " + (r.in_period > 0 ? "text-slate-900" : "text-slate-400"), fmt(r.in_period)),
            ])),
            el("td", "text-right tabular-nums", fmt(r.total)),
            el("td", "", goalCell(r)),
          ]),
        );
      });
      table.append(tbody);
      wrap.append(table);
      list.replaceChildren(ul, wrap);
      if (d.others) {
        list.append(
          el("p", "mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600", [
            "Fora das redes de coordenadores (administração e cabos diretos): ",
            el("strong", "tabular-nums", fmt(d.others.in_period)),
            " no período · ",
            el("strong", "tabular-nums", fmt(d.others.total)),
            " no total",
          ]),
        );
      }
      footer.replaceChildren();
      if (all.length > limit) {
        const btn = el("button", "btn btn-outline btn-sm", expanded ? "Mostrar menos" : "Ver todos (" + fmt(all.length) + ")");
        btn.type = "button";
        btn.setAttribute("aria-expanded", expanded ? "true" : "false");
        btn.addEventListener("click", () => {
          expanded = !expanded;
          paint();
        });
        footer.append(btn);
      }
    }
    paint();
  };

  R.goals_progress = (body, d) => {
    const rows = d.rows || [];
    if (!rows.length) {
      body.append(emptyBlock("flag", "Nenhuma meta individual definida", "Defina a meta de cadastros de cada membro na tela de Equipe."));
      return;
    }
    const ul = el("ul", "space-y-3.5");
    rows.forEach((r) => {
      ul.append(
        el("li", "", [
          el("div", "mb-1 flex items-baseline justify-between gap-2", [
            el("p", "min-w-0 truncate text-sm font-medium text-slate-800", [r.name, el("span", "ml-2 text-xs font-normal text-slate-500", roleLabel(r.role))]),
            el("p", "shrink-0 text-xs tabular-nums text-slate-500", [el("strong", "text-sm text-slate-900", fmtPct(r.pct)), " · " + fmt(r.total) + "/" + fmt(r.goal)]),
          ]),
          progressBar(r.pct, goalTone(r.pct)),
        ]),
      );
    });
    body.append(ul);
    if (d.without_goal > 0) {
      body.append(el("p", "mt-3 text-xs text-slate-500", fmt(d.without_goal) + (d.without_goal === 1 ? " membro sem meta definida." : " membros sem meta definida.")));
    }
  };

  // --- Evolução
  R.timeline = (body, d, w, ctx) => {
    const points = d.points || [];
    if (!d.total) {
      body.append(emptyBlock("chart-line", "Nenhum cadastro no período", periodLabel(d.period)));
      return;
    }
    const delta = d.previous_total > 0 ? ((d.total - d.previous_total) / d.previous_total) * 100 : null;
    const trend = d.total > d.previous_total ? "up" : d.total < d.previous_total ? "down" : "flat";
    body.append(
      el("div", "mb-3 flex flex-wrap items-center gap-x-3 gap-y-1", [
        el("span", "text-2xl font-bold tabular-nums text-slate-900", fmt(d.total)),
        el("span", "text-sm text-slate-500", d.total === 1 ? "cadastro" : "cadastros"),
        trendPill(delta, trend, "vs. período anterior"),
      ]),
    );
    const box = el("div", "relative h-56 w-full @lg:h-64");
    body.append(box);
    if (!chartAvailable()) {
      box.replaceChildren(errorBlock("Não foi possível carregar a biblioteca de gráficos."));
      return;
    }
    const canvas = canvasIn(box, "Cadastros por dia: " + fmt(d.total) + " no período");
    const many = points.length > 45;
    ctx.track(
      new window.Chart(canvas, {
        type: "line",
        data: {
          labels: points.map((p) => shortDate(p.date)),
          datasets: [
            {
              label: "Cadastros",
              data: points.map((p) => p.count),
              borderColor: PALETTE[0],
              backgroundColor: "rgba(79, 70, 229, 0.12)",
              fill: true,
              tension: 0.3,
              borderWidth: 2,
              pointRadius: many ? 0 : 3,
              pointHoverRadius: 5,
              pointBackgroundColor: "#ffffff",
              pointBorderColor: PALETTE[0],
              pointBorderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              ...TOOLTIP,
              callbacks: {
                title: (items) => (points[items[0].dataIndex] ? longDate(points[items[0].dataIndex].date) : ""),
                label: (item) => fmt(item.parsed.y) + (item.parsed.y === 1 ? " cadastro" : " cadastros"),
              },
            },
          },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } },
            y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#f1f5f9" }, border: { display: false } },
          },
        },
      }),
    );
  };

  // --- Listas com barras (bairro / cidade)
  function barList(d, noun, emptyText) {
    const rows = d.rows || [];
    const wrap = el("div");
    if (!rows.length) {
      wrap.append(emptyBlock("map-pin", "Sem dados", emptyText));
      return wrap;
    }
    const max = Math.max(1, ...rows.map((r) => r.count));
    const ul = el("ul", "space-y-3");
    rows.forEach((r) => {
      ul.append(
        el("li", "", [
          el("div", "mb-1 flex items-baseline justify-between gap-3", [
            el("span", "min-w-0 truncate text-sm text-slate-700", r.label),
            el("span", "shrink-0 text-sm tabular-nums text-slate-900", [el("strong", "", fmt(r.count)), el("span", "ml-1.5 text-xs text-slate-500", fmtPct(percentOf(r.count, d.total)))]),
          ]),
          progressBar(percentOf(r.count, max), "brand"),
        ]),
      );
    });
    wrap.append(ul);
    const notes = [];
    if (d.others > 0) notes.push("Outros (" + fmt(d.others_categories) + " " + noun.plural + "): " + fmt(d.others));
    if (d.missing > 0) notes.push("Sem " + noun.singular + " informado: " + fmt(d.missing));
    if (notes.length) wrap.append(el("p", "mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500", notes.join(" · ")));
    return wrap;
  }

  R.by_neighborhood = (body, d) => {
    body.append(barList(d, { singular: "bairro", plural: "bairros" }, "Nenhum apoiador com bairro informado."));
  };
  R.by_city = (body, d) => {
    body.append(barList(d, { singular: "cidade", plural: "cidades" }, "Nenhum apoiador com cidade informada."));
  };

  // --- Rosquinhas (gênero / apoio / origem)
  function donut(body, d, ctx, colorOf, label) {
    const rows = d.rows || [];
    if (!d.total) {
      body.append(emptyBlock("chart-pie", "Sem dados", "Nenhum apoiador corresponde a este recorte."));
      return;
    }
    const colors = rows.map((r, i) => colorOf(r, i));
    const wrap = el("div", "flex flex-col items-center gap-4 @sm:flex-row");
    const box = el("div", "relative size-40 shrink-0");
    wrap.append(box);
    const legend = el("ul", "w-full min-w-0 flex-1 space-y-2");
    rows.forEach((r, i) => {
      const dot = el("span", "size-2.5 shrink-0 rounded-full");
      dot.style.backgroundColor = colors[i];
      legend.append(
        el("li", "flex items-center gap-2 text-sm", [
          dot,
          el("span", "min-w-0 flex-1 truncate " + (r.count ? "text-slate-700" : "text-slate-400"), r.label),
          el("span", "font-medium tabular-nums " + (r.count ? "text-slate-900" : "text-slate-400"), fmt(r.count)),
          el("span", "w-12 text-right text-xs tabular-nums text-slate-500", fmtPct(percentOf(r.count, d.total))),
        ]),
      );
    });
    wrap.append(legend);
    body.append(wrap);

    if (!chartAvailable()) {
      box.replaceChildren(errorBlock("Gráfico indisponível."));
      return;
    }
    const canvas = canvasIn(box, label + ": " + rows.map((r) => r.label + " " + fmt(r.count)).join(", "));
    box.append(
      el("div", "pointer-events-none absolute inset-0 flex flex-col items-center justify-center", [
        el("span", "text-xl font-bold tabular-nums text-slate-900", fmt(d.total)),
        el("span", "text-[11px] text-slate-500", "apoiadores"),
      ]),
    );
    ctx.track(
      new window.Chart(canvas, {
        type: "doughnut",
        data: {
          labels: rows.map((r) => r.label),
          datasets: [{ data: rows.map((r) => r.count), backgroundColor: colors, borderColor: "#ffffff", borderWidth: 2, hoverOffset: 4 }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "66%",
          plugins: {
            legend: { display: false },
            tooltip: {
              ...TOOLTIP,
              callbacks: { label: (item) => item.label + ": " + fmt(item.parsed) + " (" + fmtPct(percentOf(item.parsed, d.total)) + ")" },
            },
          },
        },
      }),
    );
  }

  const categorical = (r, i) => (r.key === "unknown" ? UNKNOWN_COLOR : PALETTE[i % PALETTE.length]);
  R.by_gender = (body, d, w, ctx) => donut(body, d, ctx, categorical, "Apoiadores por gênero");
  R.by_source = (body, d, w, ctx) => donut(body, d, ctx, categorical, "Apoiadores por origem do cadastro");
  R.by_support = (body, d, w, ctx) =>
    donut(body, d, ctx, (r, i) => (r.key === "unknown" ? UNKNOWN_COLOR : SUPPORT_COLORS[r.key] || PALETTE[i % PALETTE.length]), "Apoiadores por nível de apoio");

  // --- Faixa etária
  R.by_age = (body, d, w, ctx) => {
    const rows = d.rows || [];
    if (!d.total) {
      body.append(emptyBlock("cake", "Sem dados", "Nenhum apoiador corresponde a este recorte."));
      return;
    }
    const box = el("div", "relative h-52 w-full");
    body.append(box);
    const unknown = rows.find((r) => r.key === "unknown");
    if (unknown && unknown.count > 0) {
      body.append(el("p", "mt-2 text-xs text-slate-500", fmt(unknown.count) + " apoiador(es) sem data de nascimento informada."));
    }
    if (!chartAvailable()) {
      box.replaceChildren(errorBlock("Gráfico indisponível."));
      return;
    }
    const canvas = canvasIn(box, "Apoiadores por faixa etária: " + rows.map((r) => r.label + " " + fmt(r.count)).join(", "));
    ctx.track(
      new window.Chart(canvas, {
        type: "bar",
        data: {
          labels: rows.map((r) => r.label),
          datasets: [
            {
              label: "Apoiadores",
              data: rows.map((r) => r.count),
              backgroundColor: rows.map((r) => (r.key === "unknown" ? UNKNOWN_COLOR : PALETTE[0])),
              borderRadius: 6,
              maxBarThickness: 44,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              ...TOOLTIP,
              callbacks: { label: (item) => fmt(item.parsed.y) + " (" + fmtPct(percentOf(item.parsed.y, d.total)) + ")" },
            },
          },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#f1f5f9" }, border: { display: false } },
          },
        },
      }),
    );
  };

  // --- Últimos cadastros
  R.recent_voters = (body, d) => {
    if (d.locked) {
      body.append(lockedBlock("Você não tem permissão para ver a lista de apoiadores."));
      return;
    }
    const rows = d.rows || [];
    if (!rows.length) {
      body.append(emptyBlock("users-round", "Nenhum cadastro ainda", "Os apoiadores cadastrados aparecem aqui."));
      return;
    }
    const ul = el("ul", "divide-y divide-slate-100");
    rows.forEach((r) => {
      const href = safePath(r.url);
      const place = [r.neighborhood, r.city].filter(Boolean).join(", ");
      const nameEl = href ? el("a", "link truncate", r.name) : el("span", "truncate font-medium text-slate-900", r.name);
      if (href) nameEl.href = href;
      const time = el("span", "shrink-0 text-xs text-slate-500", timeAgo(r.created_at));
      time.title = fullDateTime(r.created_at);
      ul.append(
        el("li", "flex items-center gap-3 py-2.5", [
          el("span", "avatar", initials(r.name)),
          el("div", "min-w-0 flex-1", [
            el("div", "flex min-w-0", nameEl),
            el("p", "truncate text-xs text-slate-500", [place || "Sem bairro informado", r.registered_by ? " · por " + r.registered_by : ""].join("")),
          ]),
          time,
        ]),
      );
    });
    body.append(ul);
  };

  // --- WhatsApp
  const STATUS_TONES = {
    DRAFT: "badge badge-gray",
    SCHEDULED: "badge badge-blue",
    RUNNING: "badge badge-brand",
    PAUSED: "badge badge-yellow",
    COMPLETED: "badge badge-green",
    CANCELLED: "badge badge-gray",
    FAILED: "badge badge-red",
  };

  R.broadcasts = (body, d) => {
    if (d.locked) {
      body.append(lockedBlock("Você não tem permissão para ver os disparos de WhatsApp."));
      return;
    }
    const recent = d.recent || [];
    if (!d.sent && !d.failed && !d.pending && !recent.length) {
      body.append(emptyBlock("send", "Nenhum disparo no período", "Quando houver mensagens enviadas, os resultados aparecem aqui."));
      return;
    }
    body.append(
      el("div", "grid grid-cols-2 gap-3 @2xl:grid-cols-4", [
        statTile("Enviadas", fmt(d.sent), d.pending ? fmt(d.pending) + " na fila" : periodLabel(d.period)),
        statTile("Entregues", fmt(d.delivered), "Taxa de entrega: " + fmtPct(d.delivery_rate)),
        statTile("Lidas", fmt(d.read), "Taxa de leitura: " + fmtPct(d.read_rate)),
        statTile("Falhas", fmt(d.failed), d.failed ? "Veja os detalhes em Disparos" : "Sem falhas", d.failed ? "text-red-600" : "text-slate-900"),
      ]),
    );
    if (d.sent > 0) {
      body.append(
        el("div", "mt-4 grid gap-3 @lg:grid-cols-2", [
          el("div", "", [
            el("div", "mb-1 flex justify-between text-xs text-slate-600", [el("span", "", "Entregues / enviadas"), el("strong", "tabular-nums", fmtPct(d.delivery_rate))]),
            progressBar(d.delivery_rate || 0, "green"),
          ]),
          el("div", "", [
            el("div", "mb-1 flex justify-between text-xs text-slate-600", [el("span", "", "Lidas / entregues"), el("strong", "tabular-nums", fmtPct(d.read_rate))]),
            progressBar(d.read_rate || 0, "brand"),
          ]),
        ]),
      );
    }
    if (recent.length) {
      const ul = el("ul", "mt-4 divide-y divide-slate-100 border-t border-slate-100");
      recent.forEach((b) => {
        const counts = [fmt(b.sent_count) + " env.", fmt(b.delivered_count) + " entr.", fmt(b.read_count) + " lidas"];
        if (b.failed_count) counts.push(fmt(b.failed_count) + " falhas");
        ul.append(
          el("li", "flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5", [
            el("div", "min-w-0 flex-1 basis-40", [
              el("p", "truncate text-sm font-medium text-slate-900", b.name),
              el("p", "truncate text-xs text-slate-500", fmt(b.total_recipients) + " destinatário(s) · " + counts.join(" · ")),
            ]),
            el("span", STATUS_TONES[b.status] || "badge badge-gray", b.status_label),
            el("span", "w-24 text-right text-xs text-slate-500", timeAgo(b.created_at)),
          ]),
        );
      });
      body.append(el("p", "mt-4 mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase", "Últimos disparos"), ul);
    }
    if (d.scope === "own") {
      body.append(el("p", "mt-3 text-xs text-slate-500", "Mostrando apenas os disparos criados por você."));
    }
  };

  // --- Recado
  R.note = (body, d, w) => {
    const text = ((w.config && w.config.text) || "").trim();
    if (!text) {
      body.append(el("p", "text-sm text-slate-400", "Nenhum recado escrito."));
      return;
    }
    body.append(el("div", "border-l-4 border-brand-500 pl-4 text-sm leading-relaxed break-words whitespace-pre-line text-slate-700", text));
  };

  // ------------------------------------------------------------------ Exportação
  D.el = el;
  D.append = append;
  D.icon = iconNode;
  D.iconHtml = iconHtml;
  D.fmt = fmt;
  D.fmtPct = fmtPct;
  D.timeAgo = timeAgo;
  D.periodLabel = periodLabel;
  D.skeleton = skeleton;
  D.emptyBlock = emptyBlock;
  D.errorBlock = errorBlock;
  D.renderers = R;
  D.PERIOD_LABELS = PERIOD_LABELS;
})();
