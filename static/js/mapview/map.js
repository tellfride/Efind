/* E-Find — Mapa territorial (Leaflet + Alpine).
 *
 * Busca os dados agregados em /api/painel/mapa/dados/ com os filtros da URL da página e desenha:
 *   - Bairros: círculos no centroide de cada bairro (raio ∝ √total, cor pela escala enviada pelo servidor)
 *   - Pontos : agrupamento (markercluster) de pontos individuais, sem nenhum dado pessoal
 *   - Calor  : mapa de calor
 *
 * Regras de segurança/privacidade:
 *   - nenhum texto vindo do servidor vira HTML: popups, tooltips e ícones são nós DOM (textContent);
 *   - a lista dos bairros é renderizada pelo Alpine com x-text (que também escapa);
 *   - os pontos não têm nome nem telefone, só id e coordenadas aproximadas (CEP/logradouro).
 *
 * Os objetos do Leaflet e as listas grandes (pontos) ficam em variáveis de closure, fora da reatividade do Alpine.
 */
(function () {
  "use strict";

  const STORAGE_MODE = "efind:mapa:modo";
  const STORAGE_BASEMAP = "efind:mapa:base";
  const RANKING_LIMIT = 200; // itens desenhados no ranking (a busca refina o restante)
  const WITHOUT_GEO_PREVIEW = 8;

  const numberFmt = new Intl.NumberFormat("pt-BR");
  const percentFmt = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  function fmt(n) {
    return numberFmt.format(Number(n) || 0);
  }
  function readStorage(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }
  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {
      /* armazenamento indisponível (modo privado): apenas não lembra a preferência */
    }
  }
  function norm(s) {
    return String(s || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();
  }
  /** Cria um elemento com texto SEMPRE como textContent (nunca HTML). */
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function readConfig() {
    const node = document.getElementById("map-config");
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (e) {
      return null;
    }
  }
  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  document.addEventListener("alpine:init", () => {
    const Alpine = window.Alpine;

    // Filtros recolhidos no celular; sempre visíveis no desktop
    Alpine.data("mapFilters", () => ({
      open: false,
      desktop: false,
      init() {
        const mq = window.matchMedia("(min-width: 1024px)");
        this.desktop = mq.matches;
        const onChange = (e) => {
          this.desktop = e.matches;
        };
        if (mq.addEventListener) mq.addEventListener("change", onChange);
        else if (mq.addListener) mq.addListener(onChange);
      },
      get visible() {
        return this.open || this.desktop;
      },
    }));

    Alpine.data("territorialMap", () => {
      const cfg = readConfig() || {};
      const basemaps = cfg.basemaps || {};
      const modeValues = (cfg.modes || []).map((m) => m.value);

      // --- estado fora da reatividade do Alpine ---
      let vm = null; // o componente (proxy reativo), para callbacks do Leaflet
      let map = null;
      let tileLayer = null;
      let controller = null;
      let resizeObserver = null;
      let focusTimer = null;
      let data = null; // última resposta do servidor (crua)
      let baseFilters = {}; // filtros da URL, para montar o link "Ver eleitores"
      const layers = { bairros: null, pontos: null, calor: null }; // camadas já construídas para `data`
      const markers = new Map(); // chave do bairro -> L.CircleMarker

      /** Querystring da API: reconstruída só com filtros válidos ("Localização no mapa" não se aplica ao mapa). */
      function readFilters() {
        const E = window.EFind;
        const params = new URLSearchParams(window.location.search);
        if (!E || !E.paramsToFilters || !E.filtersToParams) return { filters: {}, query: "" };
        const filters = E.paramsToFilters(params);
        delete filters.has_geo;
        return { filters: filters, query: E.filtersToParams(filters).toString() };
      }

      /** Link para a lista de eleitores do bairro (null sem permissão ou para "Bairro não informado"). */
      function votersLink(n) {
        const E = window.EFind;
        if (!data || !data.can_view_voters || !n.known || !E || !E.filtersToParams) return null;
        const filters = Object.assign({}, baseFilters, { neighborhoods: [n.name] });
        if (n.city) filters.cities = [n.city];
        else delete filters.cities;
        const query = E.filtersToParams(filters).toString();
        return (cfg.votersUrl || "/painel/eleitores/") + (query ? "?" + query : "");
      }

      // ------------------------------------------------------------------ popups e ícones (nós DOM)
      function neighborhoodPopup(n) {
        const root = el("div", "mv-popup");
        const head = el("div");
        head.append(el("p", "mv-popup-title", n.name), el("p", "mv-popup-sub", n.city || "Cidade não informada"));
        root.append(head);

        const grid = el("dl", "mv-popup-grid");
        const row = (label, value) => grid.append(el("dt", "", label), el("dd", "", fmt(value)));
        row("Total de eleitores", n.count);
        row("Aptos a WhatsApp", n.messageable);
        row("Apoiadores", n.supporters);
        if (n.count - n.mapped > 0) row("Sem localização no mapa", n.count - n.mapped);
        root.append(grid);

        if (n.top_members && n.top_members.length) {
          const box = el("div");
          box.append(el("p", "mv-popup-label", "Quem mais cadastrou"));
          const list = el("ol", "mv-popup-list");
          n.top_members.forEach((m, i) => {
            const item = el("li");
            item.append(el("span", "mv-popup-name", i + 1 + ". " + m.name), el("span", "mv-popup-num", fmt(m.count)));
            list.append(item);
          });
          box.append(list);
          root.append(box);
        }

        const href = votersLink(n);
        if (href) {
          const link = el("a", "efind-map-link", "Ver eleitores →");
          link.href = href;
          root.append(link);
        }
        return root;
      }

      function neighborhoodTooltip(n) {
        return el("span", "", n.name + " · " + fmt(n.count));
      }

      function pointPopup(p) {
        const root = el("div", "mv-popup");
        const head = el("div");
        head.append(el("p", "mv-popup-title", "Eleitor cadastrado"), el("p", "mv-popup-sub", "Localização aproximada (CEP/logradouro)."));
        root.append(head);
        if (data && data.can_view_voters) {
          const link = el("a", "efind-map-link", "Ver cadastro →");
          link.href = (cfg.votersUrl || "/painel/eleitores/") + encodeURIComponent(p.id) + "/";
          root.append(link);
        }
        return root;
      }

      function clusterIcon(cluster) {
        const count = cluster.getChildCount();
        const size = count < 10 ? "sm" : count < 100 ? "md" : "lg";
        const px = size === "sm" ? 34 : size === "md" ? 42 : 52;
        const label = count >= 10000 ? Math.round(count / 1000) + " mil" : fmt(count);
        return window.L.divIcon({
          html: el("span", "", label),
          className: "efind-cluster efind-cluster-" + size,
          iconSize: window.L.point(px, px),
        });
      }

      // ------------------------------------------------------------------ camadas
      function buildNeighborhoodLayer() {
        const L = window.L;
        const group = L.layerGroup();
        // O servidor ordena do maior para o menor: os círculos pequenos entram por último e ficam por cima
        data.neighborhoods.forEach((n) => {
          const marker = L.circleMarker([n.lat, n.lng], {
            radius: n.radius,
            color: "#ffffff",
            weight: 1.5,
            fillColor: n.color,
            fillOpacity: 0.82,
          });
          marker.bindTooltip(() => neighborhoodTooltip(n), { direction: "top", offset: [0, -n.radius], opacity: 1 });
          marker.bindPopup(() => neighborhoodPopup(n), { minWidth: 220, maxWidth: 300, autoPanPadding: [16, 16] });
          marker.on("click", () => vm.select(n.key));
          markers.set(n.key, marker);
          group.addLayer(marker);
        });
        return group;
      }

      function buildClusterLayer() {
        const L = window.L;
        if (!data.points.length || !L.markerClusterGroup) return null;
        const icon = L.divIcon({ className: "efind-point", html: "", iconSize: [14, 14], iconAnchor: [7, 7], popupAnchor: [0, -8] });
        const group = L.markerClusterGroup(
          Object.assign({ chunkedLoading: true, showCoverageOnHover: false, spiderfyOnMaxZoom: true, iconCreateFunction: clusterIcon }, cfg.clusterOptions || {}),
        );
        group.addLayers(
          data.points.map((p) => L.marker([p.lat, p.lng], { icon: icon, keyboard: false }).bindPopup(() => pointPopup(p), { minWidth: 180 })),
        );
        return group;
      }

      function buildHeatLayer() {
        const L = window.L;
        if (!data.points.length || !L.heatLayer) return null;
        const latlngs = data.points.map((p) => [p.lat, p.lng, 1]);
        return L.heatLayer(latlngs, Object.assign({}, cfg.heatOptions || {}, { gradient: cfg.heatGradient }));
      }

      function layerFor(mode) {
        if (!layers[mode]) {
          layers[mode] = mode === "pontos" ? buildClusterLayer() : mode === "calor" ? buildHeatLayer() : buildNeighborhoodLayer();
        }
        return layers[mode];
      }

      /** Descarta as camadas construídas (novos dados). */
      function dropLayers() {
        Object.keys(layers).forEach((mode) => {
          if (layers[mode] && map && map.hasLayer(layers[mode])) map.removeLayer(layers[mode]);
          layers[mode] = null;
        });
        markers.clear();
      }

      function renderLayer() {
        if (!map || !data) return;
        Object.keys(layers).forEach((mode) => {
          if (layers[mode] && map.hasLayer(layers[mode])) map.removeLayer(layers[mode]);
        });
        const layer = layerFor(vm.mode);
        if (layer) map.addLayer(layer);
        restyle(vm.selectedKey, true);
      }

      function restyle(key, selected) {
        const marker = key ? markers.get(key) : null;
        if (!marker) return;
        marker.setStyle({ color: selected ? "#0f172a" : "#ffffff", weight: selected ? 3 : 1.5 });
        if (selected && map && map.hasLayer(marker)) marker.bringToFront();
      }

      function applyBasemap(key) {
        if (!map) return;
        const base = basemaps[key];
        if (!base) return;
        if (tileLayer) map.removeLayer(tileLayer);
        tileLayer = window.L.tileLayer(base.url, { attribution: base.attribution, subdomains: base.subdomains, maxZoom: base.maxZoom });
        tileLayer.addTo(map);
        tileLayer.bringToBack();
      }

      function setupMap(container) {
        const L = window.L;
        if (!L) {
          vm.error = "Não foi possível carregar a biblioteca do mapa. Recarregue a página.";
          vm.loading = false;
          return false;
        }
        map = L.map(container, { center: cfg.center, zoom: cfg.zoom, minZoom: 3, maxZoom: 19, preferCanvas: true });
        applyBasemap(vm.basemap);
        if (typeof ResizeObserver !== "undefined") {
          resizeObserver = new ResizeObserver(() => map.invalidateSize());
          resizeObserver.observe(container);
        }
        return true;
      }

      function fitToData() {
        if (!map) return;
        map.invalidateSize();
        if (data && data.bounds) map.fitBounds(data.bounds, { padding: [32, 32], maxZoom: cfg.fitMaxZoom });
        else map.setView(cfg.center, cfg.zoom);
      }

      return {
        // --- estado exibido na página ---
        mode: cfg.defaultMode || "bairros",
        basemap: cfg.defaultBasemap || "ruas",
        loading: true,
        loaded: false,
        error: "",
        totals: { voters: 0, with_geo: 0, without_geo: 0, approximate: 0 },
        neighborhoods: [],
        withoutGeo: [],
        legendBins: [],
        maxCount: 0,
        truncated: false,
        pointsShown: 0,
        hasBounds: false,
        canViewVoters: false,
        selectedKey: null,
        query: "",
        showAllWithoutGeo: false,
        legendOpen: true,

        init() {
          vm = this;
          const savedMode = readStorage(STORAGE_MODE);
          if (modeValues.includes(savedMode)) this.mode = savedMode;
          const savedBase = readStorage(STORAGE_BASEMAP);
          if (savedBase && basemaps[savedBase]) this.basemap = savedBase;
          this.$nextTick(() => {
            if (setupMap(this.$refs.map)) this.load();
          });
        },

        destroy() {
          if (controller) controller.abort();
          if (resizeObserver) resizeObserver.disconnect();
          window.clearTimeout(focusTimer);
          if (map) map.remove();
          map = null;
        },

        // --- dados ---
        async load() {
          if (controller) controller.abort();
          const mine = new AbortController();
          controller = mine;
          this.loading = true;
          this.error = "";
          try {
            const read = readFilters();
            baseFilters = read.filters;
            const res = await fetch((cfg.dataUrl || "") + (read.query ? "?" + read.query : ""), {
              headers: { Accept: "application/json" },
              credentials: "same-origin",
              cache: "no-store",
              signal: mine.signal,
            });
            if (res.status === 401) {
              window.location.assign((cfg.loginUrl || "/login/") + "?next=" + encodeURIComponent(window.location.pathname + window.location.search));
              return;
            }
            let body = null;
            try {
              body = await res.json();
            } catch (e) {
              body = null;
            }
            if (!res.ok) throw new Error((body && body.error) || "Não foi possível carregar os dados do mapa.");
            if (!body || !body.totals || !Array.isArray(body.neighborhoods)) throw new Error("Resposta inválida do servidor.");
            this.apply(body);
          } catch (err) {
            if (mine.signal.aborted) return;
            this.error =
              err && err.name !== "TypeError" && err.message ? err.message : "Falha de conexão. Verifique sua internet e tente novamente.";
          } finally {
            if (controller === mine) this.loading = false;
          }
        },

        apply(body) {
          data = body;
          dropLayers();
          this.totals = body.totals;
          this.neighborhoods = body.neighborhoods;
          this.withoutGeo = body.neighborhoods_without_geo || [];
          this.legendBins = (body.legend && body.legend.bins) || [];
          this.maxCount = (body.legend && body.legend.max_count) || 0;
          this.truncated = !!body.truncated;
          this.pointsShown = body.points.length;
          this.hasBounds = !!body.bounds;
          this.canViewVoters = !!body.can_view_voters;
          if (this.selectedKey && !body.neighborhoods.some((n) => n.key === this.selectedKey)) this.selectedKey = null;
          this.loaded = true;
          renderLayer();
          fitToData();
        },

        // --- ações da barra de ferramentas ---
        setMode(mode) {
          if (!modeValues.includes(mode) || mode === this.mode) return;
          this.mode = mode;
          writeStorage(STORAGE_MODE, mode);
          renderLayer();
        },
        setBasemap(key) {
          if (!basemaps[key] || key === this.basemap) return;
          this.basemap = key;
          writeStorage(STORAGE_BASEMAP, key);
          applyBasemap(key);
        },
        recenter() {
          fitToData();
        },
        reload() {
          // Sem mapa (biblioteca não carregou) só uma nova carga da página resolve
          if (!map) window.location.reload();
          else this.load();
        },

        // --- bairros ---
        select(key) {
          if (this.selectedKey === key) return;
          restyle(this.selectedKey, false);
          this.selectedKey = key;
          restyle(key, true);
        },
        /** Voa até o bairro escolhido no ranking e abre o popup dele. */
        focusNeighborhood(key) {
          const n = data && data.neighborhoods.find((x) => x.key === key);
          if (!n || !map) return;
          if (this.mode !== "bairros") this.setMode("bairros");
          this.select(key);

          // No celular o painel fica abaixo do mapa: traz o mapa para a tela
          const area = this.$refs.mapArea;
          if (area) {
            const rect = area.getBoundingClientRect();
            if (rect.top < 64 || rect.bottom > window.innerHeight) {
              area.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "center" });
            }
          }

          let done = false;
          const open = () => {
            if (done) return;
            done = true;
            window.clearTimeout(focusTimer);
            map.off("moveend", open);
            const marker = markers.get(key);
            if (marker && map.hasLayer(marker)) marker.openPopup();
          };
          window.clearTimeout(focusTimer);
          focusTimer = window.setTimeout(open, 1600);
          map.once("moveend", open);
          map.flyTo([n.lat, n.lng], Math.max(map.getZoom(), cfg.focusZoom || 14), { duration: prefersReducedMotion() ? 0 : 0.8 });
        },

        // --- derivados para o painel lateral ---
        get isEmpty() {
          return this.loaded && !this.error && this.totals.with_geo === 0;
        },
        get emptyDescription() {
          return this.totals.voters > 0
            ? fmt(this.totals.voters) + " eleitor(es) encontrado(s) ainda sem localização (CEP ausente ou aguardando processamento)."
            : "Ajuste os filtros ou cadastre eleitores com CEP para vê-los no mapa.";
        },
        get rankingAll() {
          const q = norm(this.query.trim());
          const all = this.neighborhoods.map((n, i) => ({ n: n, rank: i + 1 }));
          return q ? all.filter((item) => norm(item.n.name + " " + item.n.city).includes(q)) : all;
        },
        get ranking() {
          return this.rankingAll.slice(0, RANKING_LIMIT);
        },
        get withoutGeoVisible() {
          return this.showAllWithoutGeo ? this.withoutGeo : this.withoutGeo.slice(0, WITHOUT_GEO_PREVIEW);
        },
        get withoutGeoSum() {
          return this.withoutGeo.reduce((sum, item) => sum + item.count, 0);
        },
        get legendTitle() {
          return this.mode === "bairros" ? "Eleitores por bairro" : this.mode === "pontos" ? "Eleitores" : "Concentração";
        },
        get heatGradientCss() {
          const stops = Object.entries(cfg.heatGradient || {})
            .sort((a, b) => Number(a[0]) - Number(b[0]))
            .map((entry) => entry[1] + " " + Number(entry[0]) * 100 + "%");
          return "linear-gradient(to right, " + stops.join(", ") + ")";
        },
        get coveragePct() {
          return this.totals.voters > 0 ? this.pct((this.totals.with_geo / this.totals.voters) * 100) : "0,0%";
        },

        // --- formatação ---
        fmt: fmt,
        pct(value) {
          return percentFmt.format(Number(value) || 0) + "%";
        },
        sharePct(count) {
          return this.totals.voters > 0 ? this.pct((count / this.totals.voters) * 100) : "0,0%";
        },
        barWidth(count) {
          return this.maxCount > 0 ? Math.min(100, (count / this.maxCount) * 100).toFixed(1) : "0";
        },
      };
    });
  });
})();
