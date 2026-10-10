// Copia bibliotecas JS/CSS e ícones Lucide de node_modules para static/ (arquivos versionados no git).
//   npm run vendor                      → copia tudo (bibliotecas + ícones de scripts/icons.txt)
//   node scripts/vendor.mjs --icon a b  → copia só os ícones indicados (sem editar nenhum arquivo versionado)
import { cpSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const nm = (...p) => join(root, "node_modules", ...p);
const out = (...p) => join(root, "static", ...p);

function copy(from, to) {
  if (!existsSync(from)) throw new Error(`Arquivo não encontrado: ${from}`);
  mkdirSync(dirname(to), { recursive: true });
  cpSync(from, to, { recursive: true });
}

function copyIcons(names) {
  const missing = [];
  for (const name of names) {
    const src = nm("lucide-static", "icons", `${name}.svg`);
    if (existsSync(src)) copy(src, out("icons", `${name}.svg`));
    else missing.push(name);
  }
  if (missing.length) console.warn(`Ícones inexistentes no Lucide: ${missing.join(", ")}`);
  console.log(`Ícones copiados: ${names.length - missing.length}`);
}

const args = process.argv.slice(2);
if (args[0] === "--icon") {
  copyIcons(args.slice(1));
} else {
  copy(nm("htmx.org", "dist", "htmx.min.js"), out("vendor", "htmx.min.js"));
  copy(nm("alpinejs", "dist", "cdn.min.js"), out("vendor", "alpine.min.js"));
  copy(nm("chart.js", "dist", "chart.umd.min.js"), out("vendor", "chart.umd.min.js"));
  copy(nm("sortablejs", "Sortable.min.js"), out("vendor", "Sortable.min.js"));
  copy(nm("leaflet", "dist", "leaflet.js"), out("vendor", "leaflet", "leaflet.js"));
  copy(nm("leaflet", "dist", "leaflet.css"), out("vendor", "leaflet", "leaflet.css"));
  copy(nm("leaflet", "dist", "images"), out("vendor", "leaflet", "images"));
  copy(nm("leaflet.markercluster", "dist", "leaflet.markercluster.js"), out("vendor", "leaflet", "leaflet.markercluster.js"));
  copy(nm("leaflet.markercluster", "dist", "MarkerCluster.css"), out("vendor", "leaflet", "MarkerCluster.css"));
  copy(nm("leaflet.markercluster", "dist", "MarkerCluster.Default.css"), out("vendor", "leaflet", "MarkerCluster.Default.css"));
  copy(nm("leaflet.heat", "dist", "leaflet-heat.js"), out("vendor", "leaflet", "leaflet-heat.js"));
  console.log("Bibliotecas copiadas para static/vendor");
  const names = readFileSync(join(root, "scripts", "icons.txt"), "utf8").split(/\s+/).filter(Boolean);
  copyIcons([...new Set(names)]);
}
