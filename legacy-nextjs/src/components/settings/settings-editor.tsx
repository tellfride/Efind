"use client";

import * as React from "react";
import { startTransition, useActionState, useEffect, useRef, useState } from "react";
import { AlertTriangle, ExternalLink, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { initialActionResult, type ActionResult } from "@/lib/action-result";
import {
  DEFAULT_CONSENT_TEXT,
  OFFICE_LABELS,
  OFFICES,
  UFS,
  type FormConfig,
  type FormFieldMode,
  type Office,
} from "@/lib/constants";
import { updateIdentityAction, updatePublicFormAction } from "@/app/painel/configuracoes/actions";
import { ColorField } from "./color-field";
import { FormPreview } from "./form-preview";
import { LogoField, type LogoState } from "./logo-field";
import { SegmentedControl } from "./segmented-control";
import { FORM_FIELD_GROUPS, FORM_FIELD_MODE_LABELS, FORM_FIELD_MODES, SETTINGS_LIMITS as L } from "./settings-rules";

export interface EditableSettings {
  candidateName: string;
  ballotName: string;
  ballotNumber: string | null;
  party: string | null;
  office: Office;
  city: string | null;
  state: string | null;
  electionYear: number;
  voterGoal: number | null;
  primaryColor: string;
  logoUrl: string | null;
  formTitle: string | null;
  formMessage: string | null;
  formConfig: FormConfig;
  consentText: string | null;
  privacyContact: string | null;
}

const MODE_OPTIONS = FORM_FIELD_MODES.map((m) => ({ value: m, label: FORM_FIELD_MODE_LABELS[m] }));

/** Mostra toast a cada novo resultado da ação (ignora o estado inicial) */
function useResultToast(state: ActionResult, onSuccess?: () => void) {
  const handled = useRef<ActionResult>(initialActionResult);
  useEffect(() => {
    if (state === handled.current) return;
    handled.current = state;
    if (state.ok) {
      toast.success(state.message ?? "Alterações salvas.");
      onSuccess?.();
    } else if (state.error) {
      toast.error(state.error);
    }
  }, [state, onSuccess]);
}

function fe(state: ActionResult, key: string): string[] | undefined {
  return state.ok ? undefined : state.fieldErrors?.[key];
}

function counter(value: string, max: number) {
  return `${value.length}/${max}`;
}

/**
 * Editor das configurações: cartões "Identidade da campanha" e "Formulário público" + pré-visualização ao vivo.
 * Os formulários são enviados manualmente (sem reset automático do React) para preservar o que foi digitado
 * quando há erro de validação.
 */
export function SettingsEditor({
  settings,
  canEdit,
  formHref,
  infoCard,
}: {
  settings: EditableSettings;
  canEdit: boolean;
  formHref: string;
  infoCard?: React.ReactNode;
}) {
  // ---- estado compartilhado com a pré-visualização ----
  const [ballotName, setBallotName] = useState(settings.ballotName);
  const [ballotNumber, setBallotNumber] = useState(settings.ballotNumber ?? "");
  const [party, setParty] = useState(settings.party ?? "");
  const [color, setColor] = useState(settings.primaryColor);
  const [logo, setLogo] = useState<LogoState>({ mode: "keep", url: settings.logoUrl });
  const [formTitle, setFormTitle] = useState(settings.formTitle ?? "");
  const [formMessage, setFormMessage] = useState(settings.formMessage ?? "");
  const [formConfig, setFormConfig] = useState<FormConfig>(settings.formConfig);
  const [consentText, setConsentText] = useState(settings.consentText ?? "");
  const [privacyContact, setPrivacyContact] = useState(settings.privacyContact ?? "");

  const [identityDirty, setIdentityDirty] = useState(false);
  const [formDirty, setFormDirty] = useState(false);

  const [identityState, identityAction, identityPending] = useActionState(updateIdentityAction, initialActionResult);
  const [formState, formAction, formPending] = useActionState(updatePublicFormAction, initialActionResult);

  useResultToast(identityState, () => {
    setIdentityDirty(false);
    setLogo((l) => (l.mode === "keep" ? l : { mode: "keep", url: l.url }));
  });
  useResultToast(formState, () => setFormDirty(false));

  // Aviso ao sair com alterações não salvas
  useEffect(() => {
    if (!identityDirty && !formDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [identityDirty, formDirty]);

  function submitWith(action: (fd: FormData) => void) {
    return (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (!canEdit) return;
      const fd = new FormData(e.currentTarget);
      startTransition(() => action(fd));
    };
  }

  const markIdentity = () => setIdentityDirty(true);
  const markForm = () => setFormDirty(true);
  const addressHidden = formConfig.address === "hidden";

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-6">
        {/* ---------------- Identidade ---------------- */}
        <Card>
          <form onSubmit={submitWith(identityAction)} onChange={markIdentity} noValidate>
            <CardHeader>
              <CardTitle>Identidade da campanha</CardTitle>
              <CardDescription>Dados do candidato, cor e logo usados no painel, no formulário público e nos cartazes.</CardDescription>
            </CardHeader>
            <fieldset disabled={!canEdit} className="min-w-0">
              <CardContent className="space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Nome completo do candidato" htmlFor="candidateName" required error={fe(identityState, "candidateName")}>
                    <Input
                      id="candidateName"
                      name="candidateName"
                      defaultValue={settings.candidateName}
                      maxLength={L.candidateName}
                      autoComplete="off"
                      required
                    />
                  </Field>
                  <Field
                    label="Nome de urna"
                    htmlFor="ballotName"
                    required
                    hint="Como aparece na urna e nas mensagens ({{candidato}})."
                    error={fe(identityState, "ballotName")}
                  >
                    <Input
                      id="ballotName"
                      name="ballotName"
                      value={ballotName}
                      onChange={(e) => setBallotName(e.target.value)}
                      maxLength={L.ballotName}
                      autoComplete="off"
                      required
                    />
                  </Field>
                  <Field label="Número" htmlFor="ballotNumber" hint="De 2 a 5 dígitos." error={fe(identityState, "ballotNumber")}>
                    <Input
                      id="ballotNumber"
                      name="ballotNumber"
                      inputMode="numeric"
                      value={ballotNumber}
                      onChange={(e) => setBallotNumber(e.target.value.replace(/\D/g, "").slice(0, 5))}
                      maxLength={5}
                      placeholder="Ex.: 12345"
                      autoComplete="off"
                    />
                  </Field>
                  <Field label="Partido / federação" htmlFor="party" error={fe(identityState, "party")}>
                    <Input
                      id="party"
                      name="party"
                      value={party}
                      onChange={(e) => setParty(e.target.value)}
                      maxLength={L.party}
                      placeholder="Ex.: PXX"
                      autoComplete="off"
                    />
                  </Field>
                  <Field label="Cargo disputado" htmlFor="office" required error={fe(identityState, "office")}>
                    <Select id="office" name="office" defaultValue={settings.office} required>
                      {OFFICES.map((o) => (
                        <option key={o} value={o}>
                          {OFFICE_LABELS[o]}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Ano da eleição" htmlFor="electionYear" required error={fe(identityState, "electionYear")}>
                    <Input
                      id="electionYear"
                      name="electionYear"
                      type="number"
                      inputMode="numeric"
                      min={L.electionYearMin}
                      max={L.electionYearMax}
                      defaultValue={settings.electionYear}
                      required
                    />
                  </Field>
                  <Field label="Cidade" htmlFor="city" error={fe(identityState, "city")}>
                    <Input id="city" name="city" defaultValue={settings.city ?? ""} maxLength={L.city} placeholder="Ex.: Campinas" />
                  </Field>
                  <Field label="UF" htmlFor="state" error={fe(identityState, "state")}>
                    <Select id="state" name="state" defaultValue={settings.state ?? ""}>
                      <option value="">Selecione</option>
                      {UFS.map((uf) => (
                        <option key={uf} value={uf}>
                          {uf}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field
                    label="Meta de cadastros"
                    htmlFor="voterGoal"
                    hint="Total de eleitores que a campanha pretende cadastrar."
                    error={fe(identityState, "voterGoal")}
                  >
                    <Input
                      id="voterGoal"
                      name="voterGoal"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={L.voterGoalMax}
                      defaultValue={settings.voterGoal ?? ""}
                      placeholder="Ex.: 5000"
                    />
                  </Field>
                  <ColorField
                    value={color}
                    onChange={(v) => {
                      setColor(v);
                      markIdentity();
                    }}
                    error={fe(identityState, "primaryColor")}
                    disabled={!canEdit}
                  />
                </div>

                <input type="hidden" name="logoAction" value={logo.mode} />
                {logo.mode === "replace" && <input type="hidden" name="logoDataUrl" value={logo.url} />}
                <LogoField
                  value={logo}
                  savedUrl={settings.logoUrl}
                  onChange={(v) => {
                    setLogo(v);
                    markIdentity();
                  }}
                  error={fe(identityState, "logo") ?? fe(identityState, "logoDataUrl")}
                  disabled={!canEdit}
                  color={color}
                  fallback={ballotNumber.slice(0, 2) || ballotName.slice(0, 1).toUpperCase() || "?"}
                />
              </CardContent>
            </fieldset>
            {canEdit && (
              <CardFooter className="justify-between">
                <span className="text-xs text-slate-500">{identityDirty ? <Badge tone="yellow">Alterações não salvas</Badge> : null}</span>
                <Button type="submit" loading={identityPending}>
                  {!identityPending && <Save aria-hidden />}
                  {identityPending ? "Salvando..." : "Salvar identidade"}
                </Button>
              </CardFooter>
            )}
          </form>
        </Card>

        {/* ---------------- Formulário público ---------------- */}
        <Card>
          <form onSubmit={submitWith(formAction)} onChange={markForm} noValidate>
            <CardHeader>
              <CardTitle>Formulário público de cadastro</CardTitle>
              <CardDescription>
                O que o eleitor vê ao abrir o link ou o QR Code de qualquer pessoa da equipe. O cadastro fica sempre vinculado a
                quem compartilhou o link.
              </CardDescription>
            </CardHeader>
            <fieldset disabled={!canEdit} className="min-w-0">
              <CardContent className="space-y-6">
                <div className="space-y-4">
                  <Field
                    label="Título"
                    htmlFor="formTitle"
                    hint={`Opcional · ${counter(formTitle, L.formTitle)}`}
                    error={fe(formState, "formTitle")}
                  >
                    <Input
                      id="formTitle"
                      name="formTitle"
                      value={formTitle}
                      onChange={(e) => setFormTitle(e.target.value)}
                      maxLength={L.formTitle}
                      placeholder={`Ex.: Faça parte da campanha de ${ballotName || "nosso candidato"}`}
                    />
                  </Field>
                  <Field
                    label="Mensagem de boas-vindas"
                    htmlFor="formMessage"
                    hint={`Opcional · ${counter(formMessage, L.formMessage)}`}
                    error={fe(formState, "formMessage")}
                  >
                    <Textarea
                      id="formMessage"
                      name="formMessage"
                      rows={3}
                      value={formMessage}
                      onChange={(e) => setFormMessage(e.target.value)}
                      maxLength={L.formMessage}
                      placeholder="Ex.: Cadastre-se para receber novidades da campanha e participar dos nossos encontros no seu bairro."
                    />
                  </Field>
                </div>

                <div>
                  <h4 className="text-sm font-semibold text-slate-900">Campos do formulário</h4>
                  <p className="mt-0.5 text-xs text-slate-500">Nome e WhatsApp são sempre obrigatórios. Defina como os demais aparecem.</p>
                  <ul className="mt-3 divide-y divide-slate-100 rounded-lg border border-slate-200">
                    {FORM_FIELD_GROUPS.map((g) => (
                      <li key={g.key} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-800">{g.label}</p>
                          <p className="text-xs text-slate-500">{g.description}</p>
                        </div>
                        <SegmentedControl<FormFieldMode>
                          name={`formConfig.${g.key}`}
                          ariaLabel={`Campo ${g.label}`}
                          value={formConfig[g.key]}
                          options={MODE_OPTIONS}
                          disabled={!canEdit}
                          onChange={(mode) => setFormConfig((c) => ({ ...c, [g.key]: mode }))}
                        />
                      </li>
                    ))}
                  </ul>
                  {addressHidden && (
                    <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-700">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                      Sem o endereço, os novos eleitores não aparecem no mapa por bairro.
                    </p>
                  )}
                </div>

                <Field
                  label="Texto de consentimento (LGPD)"
                  htmlFor="consentText"
                  hint={
                    consentText.trim()
                      ? `Use {{candidato}} para inserir o nome de urna · ${counter(consentText, L.consentTextMax)}`
                      : "Em branco: será usado o texto padrão exibido acima. Use {{candidato}} para inserir o nome de urna."
                  }
                  error={fe(formState, "consentText")}
                >
                  <Textarea
                    id="consentText"
                    name="consentText"
                    rows={5}
                    value={consentText}
                    onChange={(e) => setConsentText(e.target.value)}
                    maxLength={L.consentTextMax}
                    placeholder={DEFAULT_CONSENT_TEXT}
                  />
                  {canEdit && consentText.trim() !== "" && (
                    <div className="pt-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (window.confirm("Substituir o texto atual pelo texto padrão de consentimento?")) {
                            setConsentText("");
                            markForm();
                          }
                        }}
                      >
                        <RotateCcw aria-hidden /> Restaurar texto padrão
                      </Button>
                    </div>
                  )}
                </Field>
                <p className="-mt-3 text-xs text-slate-500">
                  O eleitor precisa marcar o consentimento (caixa nunca pré-marcada). O aceite de mensagens de WhatsApp é
                  separado e opcional.
                </p>

                <Field
                  label="Contato do encarregado / controlador de dados"
                  htmlFor="privacyContact"
                  hint="Exibido na política de privacidade do formulário para o eleitor pedir acesso, correção ou exclusão dos dados."
                  error={fe(formState, "privacyContact")}
                >
                  <Input
                    id="privacyContact"
                    name="privacyContact"
                    value={privacyContact}
                    onChange={(e) => setPrivacyContact(e.target.value)}
                    maxLength={L.privacyContact}
                    placeholder="Ex.: Maria Souza · privacidade@suacampanha.com.br · (11) 99999-0000"
                  />
                </Field>
              </CardContent>
            </fieldset>
            {canEdit && (
              <CardFooter className="justify-between">
                <span className="text-xs text-slate-500">{formDirty ? <Badge tone="yellow">Alterações não salvas</Badge> : null}</span>
                <Button type="submit" loading={formPending}>
                  {!formPending && <Save aria-hidden />}
                  {formPending ? "Salvando..." : "Salvar formulário"}
                </Button>
              </CardFooter>
            )}
          </form>
        </Card>
      </div>

      {/* ---------------- Pré-visualização + informações ---------------- */}
      <aside className="min-w-0 space-y-6 xl:sticky xl:top-24 xl:self-start">
        <Card>
          <CardHeader>
            <CardTitle>Pré-visualização</CardTitle>
            <CardDescription>Aproximação do formulário com as alterações ainda não salvas.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="mx-auto max-w-[340px]">
              <FormPreview
                brand={{ ballotName, ballotNumber, party, primaryColor: color, logoUrl: logo.url }}
                title={formTitle}
                message={formMessage}
                formConfig={formConfig}
                consentText={consentText}
              />
            </div>
            <a
              href={formHref}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <ExternalLink className="size-4" aria-hidden /> Abrir meu formulário
            </a>
            <p className="text-center text-xs text-slate-500">O formulário real reflete apenas o que já foi salvo.</p>
          </CardContent>
        </Card>
        {infoCard}
      </aside>
    </div>
  );
}
