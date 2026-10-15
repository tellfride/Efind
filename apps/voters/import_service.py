"""Importação de apoiadores por CSV: análise (usada na pré-visualização E na importação — o servidor sempre
reexecuta tudo) e gravação em lote. A lógica de leitura/validação de cada linha está em `csv_import`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from django.db import IntegrityError, transaction

from apps.core.constants import GeoStatus, VoterSource
from apps.core.phone import normalize_br_phone

from .csv_import import (
    MAX_IMPORT_CHARS,
    MAX_IMPORT_ROWS,
    CsvParseError,
    ImportRecord,
    ParsedCsv,
    RowResult,
    auto_map_headers,
    build_import_records,
    clean_mapping,
    missing_required_fields,
    parse_csv,
    split_file_duplicates,
    validate_records,
)
from .models import Voter

PREVIEW_ROWS = 10
MAX_REPORTED_ROWS = 200  # linhas com problema listadas no resultado

# Status de cada linha na análise
ROW_OK = "ok"
ROW_INVALID = "invalid"
ROW_DUP_FILE = "duplicate_file"
ROW_DUP_CAMPAIGN = "duplicate_campaign"

IMPORT_CONSENT_TEXT = (
    "Declaração do responsável pela importação ({responsavel}): os apoiadores desta lista consentiram com o "
    "tratamento de seus dados pessoais, nos termos da LGPD."
)
IMPORT_WHATSAPP_TEXT = " Também consentiram com o recebimento de mensagens de WhatsApp."


def read_csv(text: str) -> ParsedCsv:
    """Lê o texto do CSV com os limites da importação (mensagens em pt-BR)."""
    if len(text or "") > MAX_IMPORT_CHARS:
        raise CsvParseError("Arquivo muito grande. Divida a lista em arquivos menores (até 5.000 linhas).")
    parsed = parse_csv(text or "")
    if not parsed.rows:
        raise CsvParseError("O arquivo está vazio. Cole ou envie um CSV com os apoiadores.")
    return parsed


def n_columns_of(parsed: ParsedCsv) -> int:
    return max(len(r) for r in parsed.rows)


def looks_like_header(parsed: ParsedCsv) -> bool:
    """A primeira linha parece um cabeçalho? (reconhece pelo menos uma coluna conhecida)"""
    return any(auto_map_headers(parsed.rows[0]))


def guess_mapping_from_data(row: list[str], n_columns: int) -> list[str]:
    """Sem cabeçalho: tenta achar nome, telefone e e-mail pelo conteúdo da primeira linha."""
    mapping = [""] * n_columns
    used: set[str] = set()
    for i, cell in enumerate(row[:n_columns]):
        value = (cell or "").strip()
        if not value:
            continue
        digits = "".join(c for c in value if c.isdigit())
        if "telefone" not in used and len(digits) >= 10 and normalize_br_phone(value):
            mapping[i] = "telefone"
            used.add("telefone")
        elif "email" not in used and "@" in value:
            mapping[i] = "email"
            used.add("email")
        elif "nome" not in used and len(value) >= 3 and any(c.isalpha() for c in value) and not digits:
            mapping[i] = "nome"
            used.add("nome")
    return mapping


@dataclass
class ImportAnalysis:
    parsed: ParsedCsv
    has_header: bool
    mapping: list[str]
    missing_required: list[str]  # chaves de campos obrigatórios sem coluna
    records: list[ImportRecord] = field(default_factory=list)
    results: list[RowResult] = field(default_factory=list)
    unique: list[RowResult] = field(default_factory=list)  # válidas e únicas no arquivo
    repeated: list[RowResult] = field(default_factory=list)  # telefone repetido no arquivo
    existing_phones: set[str] = field(default_factory=set)
    over_limit: bool = False

    @property
    def invalid(self) -> list[RowResult]:
        return [r for r in self.results if r.voter is None]

    @property
    def already_registered(self) -> list[RowResult]:
        return [r for r in self.unique if r.voter["phone"] in self.existing_phones]

    @property
    def to_import(self) -> list[RowResult]:
        return [r for r in self.unique if r.voter["phone"] not in self.existing_phones]

    def status_of(self, result: RowResult) -> str:
        if result.voter is None:
            return ROW_INVALID
        if any(result is r for r in self.repeated):
            return ROW_DUP_FILE
        if result.voter["phone"] in self.existing_phones:
            return ROW_DUP_CAMPAIGN
        return ROW_OK


def existing_phones_in_campaign(campaign_id, phones: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(phones), 500):
        chunk = phones[i : i + 500]
        found.update(Voter.objects.filter(campaign_id=campaign_id, phone__in=chunk).values_list("phone", flat=True))
    return found


def analyze_import(
    text: str,
    campaign_id,
    *,
    mapping=None,
    has_header: bool | None = None,
    today: date | None = None,
) -> ImportAnalysis:
    """Lê, mapeia e valida o CSV. `mapping`/`has_header` None → detecção automática.
    Levanta CsvParseError (arquivo ilegível) ou ValueError (mapeamento inválido)."""
    parsed = read_csv(text)
    n_cols = n_columns_of(parsed)
    if has_header is None:
        has_header = looks_like_header(parsed)
    if mapping is None:
        first = list(parsed.rows[0]) + [""] * (n_cols - len(parsed.rows[0]))
        mapping = auto_map_headers(first) if has_header else guess_mapping_from_data(first, n_cols)
    mapping = clean_mapping(mapping, n_cols)
    missing = missing_required_fields(mapping)
    analysis = ImportAnalysis(parsed=parsed, has_header=has_header, mapping=mapping, missing_required=missing)
    data_rows = len(parsed.rows) - (1 if has_header else 0)
    analysis.over_limit = data_rows > MAX_IMPORT_ROWS
    if missing or analysis.over_limit:
        return analysis
    analysis.records = build_import_records(parsed, mapping, has_header)
    analysis.results = validate_records(analysis.records, today)
    analysis.unique, analysis.repeated = split_file_duplicates(analysis.results)
    analysis.existing_phones = existing_phones_in_campaign(campaign_id, [r.voter["phone"] for r in analysis.unique])
    return analysis


# ---------------------------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------------------------


@dataclass
class ImportOutcome:
    total: int = 0
    imported: int = 0
    duplicates_campaign: int = 0
    duplicates_file: int = 0
    invalid: int = 0
    problems: list[dict] = field(default_factory=list)  # {"row", "kind", "reasons"} (limitado)
    warnings: int = 0

    def as_session(self) -> dict:
        return {
            "total": self.total,
            "imported": self.imported,
            "duplicates_campaign": self.duplicates_campaign,
            "duplicates_file": self.duplicates_file,
            "invalid": self.invalid,
            "warnings": self.warnings,
            "problems": self.problems,
        }


def consent_text_for(registrar_name: str, whatsapp_opt_in: bool) -> str:
    text = IMPORT_CONSENT_TEXT.format(responsavel=registrar_name)
    return text + (IMPORT_WHATSAPP_TEXT if whatsapp_opt_in else "")


def _voter_from(data: dict, *, campaign_id, registered_by, whatsapp_opt_in: bool, now: datetime, ip, consent_text: str):
    return Voter(
        campaign_id=campaign_id,
        registered_by=registered_by,
        source=VoterSource.IMPORT,
        consent_at=now,
        consent_ip=ip,
        consent_text=consent_text,
        whatsapp_opt_in=whatsapp_opt_in,
        geo_status=GeoStatus.PENDING,
        **data,
    )


def run_import(
    analysis: ImportAnalysis,
    *,
    campaign_id,
    registered_by,
    whatsapp_opt_in: bool,
    now: datetime,
    ip: str | None,
) -> ImportOutcome:
    """Grava os apoiadores válidos e novos. Telefones repetidos/já cadastrados e linhas inválidas são ignorados."""
    outcome = ImportOutcome(total=len(analysis.results))
    outcome.invalid = len(analysis.invalid)
    outcome.duplicates_file = len(analysis.repeated)
    outcome.duplicates_campaign = len(analysis.already_registered)
    outcome.warnings = sum(1 for r in analysis.results if r.voter is not None and r.warnings)

    for r in analysis.invalid:
        _report(outcome, r.row, "invalid", "; ".join(r.errors))
    for r in analysis.repeated:
        _report(outcome, r.row, "duplicate_file", "Telefone repetido no arquivo")
    for r in analysis.already_registered:
        _report(outcome, r.row, "duplicate_campaign", "Telefone já cadastrado na campanha")

    consent_text = consent_text_for(registered_by.name, whatsapp_opt_in)
    items = [
        (
            r,
            _voter_from(
                r.voter,
                campaign_id=campaign_id,
                registered_by=registered_by,
                whatsapp_opt_in=whatsapp_opt_in,
                now=now,
                ip=ip,
                consent_text=consent_text,
            ),
        )
        for r in analysis.to_import
    ]
    for i in range(0, len(items), 500):
        batch = items[i : i + 500]
        try:
            with transaction.atomic():
                Voter.objects.bulk_create([v for _, v in batch])
            outcome.imported += len(batch)
        except IntegrityError:
            # Corrida com outro cadastro do mesmo telefone: grava linha a linha e conta o que sobrou como duplicado
            for result, voter in batch:
                try:
                    with transaction.atomic():
                        voter.save(force_insert=True)
                    outcome.imported += 1
                except IntegrityError:
                    outcome.duplicates_campaign += 1
                    _report(outcome, result.row, "duplicate_campaign", "Telefone já cadastrado na campanha")
    outcome.problems.sort(key=lambda p: p["row"])
    return outcome


def _report(outcome: ImportOutcome, row: int, kind: str, reasons: str) -> None:
    if len(outcome.problems) < MAX_REPORTED_ROWS:
        outcome.problems.append({"row": row, "kind": kind, "reasons": reasons})

