"use client";

import * as React from "react";
import { ImagePlus, Loader2, RefreshCw, Trash2, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { FieldError, Label } from "@/components/ui/form";
import { cn } from "@/lib/utils";
import { processLogoFile, type ProcessedLogo } from "./logo-image";
import { LOGO_ACCEPTED_TYPES, dataUrlByteSize, formatBytes } from "./settings-rules";

export type LogoState =
  | { mode: "keep"; url: string | null }
  | { mode: "remove"; url: null }
  | { mode: "replace"; url: string; info: Omit<ProcessedLogo, "dataUrl"> };

/** Upload do logo: redimensiona no navegador e guarda a data URL para enviar com o formulário */
export function LogoField({
  value,
  savedUrl,
  onChange,
  error,
  disabled,
  fallback,
  color,
}: {
  value: LogoState;
  savedUrl: string | null;
  onChange: (value: LogoState) => void;
  error?: string[];
  disabled?: boolean;
  /** Texto exibido quando não há logo (ex.: número ou inicial) */
  fallback: string;
  color: string;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  const [localError, setLocalError] = React.useState<string | null>(null);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setLocalError(null);
    setBusy(true);
    try {
      const { dataUrl, ...info } = await processLogoFile(file);
      onChange({ mode: "replace", url: dataUrl, info });
      toast.success("Logo pronto. Salve para aplicar.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Não foi possível processar a imagem.";
      setLocalError(message);
      toast.error(message);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const url = value.url;
  const changed = value.mode !== "keep";
  const sizeLabel =
    value.mode === "replace"
      ? `${value.info.format} · ${value.info.width}×${value.info.height} px · ${formatBytes(value.info.bytes)}`
      : url
        ? `Logo atual · ${formatBytes(dataUrlByteSize(url))}`
        : "Nenhum logo enviado";

  return (
    <div className="space-y-1.5">
      <Label htmlFor="logoFile">Logo da campanha</Label>
      <div className="flex flex-col gap-4 rounded-lg border border-dashed border-slate-300 p-4 sm:flex-row sm:items-center">
        <div
          className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-slate-200"
          style={{
            backgroundImage:
              "linear-gradient(45deg,#f1f5f9 25%,transparent 25%),linear-gradient(-45deg,#f1f5f9 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#f1f5f9 75%),linear-gradient(-45deg,transparent 75%,#f1f5f9 75%)",
            backgroundPosition: "0 0,0 8px,8px -8px,-8px 0",
            backgroundSize: "16px 16px",
          }}
        >
          {busy ? (
            <Loader2 className="size-6 animate-spin text-slate-400" aria-label="Processando imagem" />
          ) : url ? (
            <img src={url} alt="Logo da campanha" className="size-full object-contain p-1.5" />
          ) : (
            <span
              className="flex size-full items-center justify-center text-2xl font-bold text-white"
              style={{ backgroundColor: color }}
              aria-hidden
            >
              {fallback}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <p className={cn("text-sm", changed ? "font-medium text-amber-700" : "text-slate-600")}>
            {value.mode === "remove" ? "O logo será removido ao salvar." : sizeLabel}
          </p>
          <p className="text-xs text-slate-500">
            PNG, JPEG ou WebP. A imagem é redimensionada para até 512 px e otimizada para no máximo 300 KB. Prefira fundo
            transparente.
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              ref={inputRef}
              id="logoFile"
              type="file"
              accept={LOGO_ACCEPTED_TYPES.join(",")}
              className="sr-only"
              disabled={disabled || busy}
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
            <Button
              variant="outline"
              size="sm"
              disabled={disabled || busy}
              onClick={() => inputRef.current?.click()}
            >
              {url ? <RefreshCw aria-hidden /> : <ImagePlus aria-hidden />}
              {url ? "Trocar logo" : "Enviar logo"}
            </Button>
            {url && (
              <Button
                variant="ghost"
                size="sm"
                className="text-red-600 hover:bg-red-50 hover:text-red-700"
                disabled={disabled || busy}
                onClick={() => {
                  if (value.mode === "replace" && !savedUrl) {
                    onChange({ mode: "keep", url: null });
                    return;
                  }
                  if (window.confirm("Remover o logo da campanha? Ele deixará de aparecer no formulário e no painel após salvar.")) {
                    onChange({ mode: "remove", url: null });
                  }
                }}
              >
                <Trash2 aria-hidden /> Remover
              </Button>
            )}
            {changed && (
              <Button
                variant="ghost"
                size="sm"
                disabled={disabled || busy}
                onClick={() => {
                  setLocalError(null);
                  onChange({ mode: "keep", url: savedUrl });
                }}
              >
                <Undo2 aria-hidden /> Desfazer
              </Button>
            )}
          </div>
        </div>
      </div>
      <FieldError messages={error ?? localError} />
    </div>
  );
}
