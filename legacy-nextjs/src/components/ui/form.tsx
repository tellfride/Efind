import * as React from "react";
import { cn } from "@/lib/utils";

const fieldBase =
  "block w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 " +
  "focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 " +
  "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500 " +
  "aria-[invalid=true]:border-red-400 aria-[invalid=true]:focus:ring-red-500/20";

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input className={cn(fieldBase, "h-10", className)} {...props} />;
}

export function Textarea({ className, rows = 4, ...props }: React.ComponentProps<"textarea">) {
  return <textarea rows={rows} className={cn(fieldBase, "py-2", className)} {...props} />;
}

export function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <select className={cn(fieldBase, "h-10 pr-8", className)} {...props}>
      {children}
    </select>
  );
}

export function Checkbox({ className, ...props }: Omit<React.ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      className={cn(
        "size-4 shrink-0 rounded border-slate-300 text-brand-600 accent-brand-600 focus:ring-2 focus:ring-brand-500/30",
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: React.ComponentProps<"label">) {
  return <label className={cn("block text-sm font-medium text-slate-700", className)} {...props} />;
}

export function FieldError({ messages, className }: { messages?: string[] | string | null; className?: string }) {
  const list = !messages ? [] : Array.isArray(messages) ? messages : [messages];
  if (!list.length) return null;
  return (
    <p className={cn("mt-1 text-xs text-red-600", className)} role="alert">
      {list[0]}
    </p>
  );
}

export interface FieldProps {
  label?: React.ReactNode;
  htmlFor?: string;
  hint?: React.ReactNode;
  error?: string[] | string | null;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}

/** Rótulo + controle + dica/erro */
export function Field({ label, htmlFor, hint, error, required, className, children }: FieldProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <Label htmlFor={htmlFor}>
          {label}
          {required && <span className="ml-0.5 text-red-500">*</span>}
        </Label>
      )}
      {children}
      {hint && !error && <p className="text-xs text-slate-500">{hint}</p>}
      <FieldError messages={error} />
    </div>
  );
}

/** Mensagem de sucesso/erro de uma Server Action */
export function FormMessage({ result, className }: { result?: { ok: boolean; message?: string; error?: string } | null; className?: string }) {
  if (!result) return null;
  if (result.ok && result.message) {
    return (
      <div className={cn("rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800", className)} role="status">
        {result.message}
      </div>
    );
  }
  if (!result.ok && result.error) {
    return (
      <div className={cn("rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800", className)} role="alert">
        {result.error}
      </div>
    );
  }
  return null;
}
