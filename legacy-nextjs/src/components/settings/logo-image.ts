// Redimensiona e recodifica o logo no navegador (canvas) para caber em 512 px e 300 KB.
// Usado apenas por componentes cliente: depende de document/canvas no momento da chamada.
import {
  LOGO_MAX_BYTES,
  LOGO_MAX_DIMENSION,
  LOGO_MAX_SOURCE_BYTES,
  dataUrlByteSize,
  fitWithin,
  formatBytes,
  isAcceptedLogoType,
  validateLogoDataUrl,
} from "./settings-rules";

export interface ProcessedLogo {
  dataUrl: string;
  width: number;
  height: number;
  bytes: number;
  format: "WebP" | "PNG";
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Não foi possível ler a imagem. Verifique se o arquivo não está corrompido."));
    };
    img.src = url;
  });
}

const DIMENSIONS = [LOGO_MAX_DIMENSION, 384, 256, 192, 128];
const QUALITIES = [0.92, 0.85, 0.75, 0.6, 0.45];

export async function processLogoFile(file: File): Promise<ProcessedLogo> {
  if (!isAcceptedLogoType(file.type)) throw new Error("Formato não suportado. Use PNG, JPEG ou WebP.");
  if (file.size > LOGO_MAX_SOURCE_BYTES) {
    throw new Error(`Arquivo muito grande (${formatBytes(file.size)}). Escolha uma imagem de até 15 MB.`);
  }
  const img = await loadImage(file);
  const srcW = img.naturalWidth;
  const srcH = img.naturalHeight;
  if (!srcW || !srcH) throw new Error("Imagem inválida.");

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Seu navegador não permite processar imagens.");

  for (const max of DIMENSIONS) {
    const { width, height } = fitWithin(srcW, srcH, max);
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, 0, 0, width, height);

    for (const quality of QUALITIES) {
      let dataUrl = canvas.toDataURL("image/webp", quality);
      let format: ProcessedLogo["format"] = "WebP";
      // Navegadores sem codificador WebP devolvem PNG
      if (!dataUrl.startsWith("data:image/webp")) {
        dataUrl = canvas.toDataURL("image/png");
        format = "PNG";
      }
      const bytes = dataUrlByteSize(dataUrl);
      if (bytes <= LOGO_MAX_BYTES && validateLogoDataUrl(dataUrl).ok) {
        return { dataUrl, width, height, bytes, format };
      }
      if (format === "PNG") break; // qualidade não se aplica ao PNG: tenta dimensão menor
    }
  }
  throw new Error("Não foi possível reduzir a imagem para até 300 KB. Tente um arquivo mais simples.");
}
