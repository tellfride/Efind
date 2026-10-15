"""Importação de apoiadores por CSV — lógica pura (sem banco).

Fluxo: `parse_csv` → `auto_map_headers`/mapeamento manual → `build_import_records` → `validate_import_record`.
O servidor SEMPRE reexecuta tudo isso na importação: a pré-visualização do navegador não é confiável.
Portado de legacy-nextjs/src/components/voters/csv-import.ts.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from apps.core.constants import UFS, Gender, SupportLevel
from apps.core.phone import normalize_br_phone
from apps.core.utils import age_from, normalize_text, serialize_tags, title_case, to_csv
from apps.geo.cep import normalize_cep

from .utils import (
    MAX_VOTER_AGE,
    MIN_VOTER_AGE,
    collapse_spaces,
    has_letter,
    is_voter_age,
    normalize_digits_field,
    parse_birth_date_input,
    smart_case,
)

MAX_IMPORT_ROWS = 5000
MAX_IMPORT_CHARS = 4_000_000  # ~4 MB de texto


@dataclass(frozen=True)
class ImportField:
    key: str
    label: str
    required: bool
    aliases: tuple[str, ...]


IMPORT_FIELDS: tuple[ImportField, ...] = (
    ImportField(
        "nome",
        "Nome",
        True,
        # colunas de planilhas antigas ou de outras fontes continuam sendo reconhecidas
        ("nome", "nomecompleto", "name", "apoiador", "nomedoapoiador", "nomeapoiador",
         "eleitor", "nomedoeleitor", "nomeeleitor"),  # fmt: skip
    ),
    ImportField(
        "telefone",
        "Telefone / WhatsApp",
        True,
        ("telefone", "celular", "whatsapp", "whats", "zap", "fone", "tel", "phone", "telefonecelular", "contato", "cel"),
    ),
    ImportField("email", "E-mail", False, ("email", "mail", "correioeletronico")),
    ImportField(
        "nascimento",
        "Data de nascimento",
        False,
        ("nascimento", "datanascimento", "datadenascimento", "dtnascimento", "dtnasc", "nasc", "datanasc", "aniversario", "birthdate"),
    ),
    ImportField("genero", "Gênero", False, ("genero", "sexo", "gender")),
    ImportField("cep", "CEP", False, ("cep", "codigopostal", "zipcode", "zip")),
    ImportField("rua", "Logradouro", False, ("rua", "logradouro", "endereco", "street", "avenida")),
    ImportField("numero", "Número", False, ("numero", "num", "nro", "n", "no", "numerocasa", "numeroresidencia")),
    ImportField("complemento", "Complemento", False, ("complemento", "compl", "apto", "apartamento")),
    ImportField("bairro", "Bairro", False, ("bairro", "distrito", "neighborhood")),
    ImportField("cidade", "Cidade", False, ("cidade", "municipio", "city", "localidade")),
    ImportField("uf", "UF", False, ("uf", "estado", "state")),
    ImportField("zona", "Zona eleitoral", False, ("zona", "zonaeleitoral")),
    ImportField("secao", "Seção eleitoral", False, ("secao", "secaoeleitoral", "sessao", "sessaoeleitoral")),
    ImportField("apoio", "Nível de apoio", False, ("apoio", "nivelapoio", "niveldeapoio", "classificacao")),
    ImportField("tags", "Tags", False, ("tags", "tag", "etiquetas", "marcadores", "grupos", "grupo")),
)
IMPORT_FIELD_KEYS = tuple(f.key for f in IMPORT_FIELDS)
IMPORT_FIELD_LABELS = {f.key: f.label for f in IMPORT_FIELDS}

SEPARATORS = (";", ",", "\t")


class CsvParseError(ValueError):
    """Arquivo ilegível (mensagem já em pt-BR, pronta para o usuário)."""


# ---------------------------------------------------------------------------------------------
# Leitura do CSV
# ---------------------------------------------------------------------------------------------


@dataclass
class ParsedCsv:
    separator: str
    rows: list[list[str]]
    lines: list[int]  # linha física (1 = primeira) onde cada registro começa


def _count_outside_quotes(line: str, ch: str) -> int:
    n, in_quotes = 0, False
    for c in line:
        if c == '"':
            in_quotes = not in_quotes
        elif c == ch and not in_quotes:
            n += 1
    return n


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("﻿") else text


_SEP_DIRECTIVE = re.compile(r"^sep=(.)[ \t]*(?:\r\n|\n|\r|$)", re.IGNORECASE)


def detect_separator(text: str) -> str:
    """Separador pela primeira linha não vazia (empate favorece ";", padrão do Excel em pt-BR)."""
    clean = _strip_bom(text)
    if (m := _SEP_DIRECTIVE.match(clean)) and m[1] in SEPARATORS:
        return m[1]
    first = next((ln for ln in re.split(r"\r\n|\n|\r", clean) if ln.strip()), "")
    counts = [(sep, _count_outside_quotes(first, sep)) for sep in SEPARATORS]
    best = max(counts, key=lambda c: c[1])  # empate → primeiro da lista (";")
    return ";" if best[1] == 0 else best[0]


def parse_csv(text: str, separator: str | None = None) -> ParsedCsv:
    """Lê CSV (RFC 4180): aspas, aspas escapadas (""), quebras de linha entre aspas, CRLF/LF/CR, BOM e a
    diretiva "sep=;" do Excel. Linhas totalmente vazias são descartadas."""
    if separator is not None and separator not in SEPARATORS:
        raise CsvParseError("Separador inválido. Use ponto e vírgula, vírgula ou tabulação.")
    src = _strip_bom(text or "").replace("\x00", "")
    sep = separator or detect_separator(src)
    first_line = 1
    if m := _SEP_DIRECTIVE.match(src):
        src = src[m.end():]
        first_line = 2

    rows: list[list[str]] = []
    lines: list[int] = []
    reader = csv.reader(io.StringIO(src, newline=""), delimiter=sep, quotechar='"', skipinitialspace=True)
    prev_end = 0
    try:
        for cells in reader:
            start = prev_end + 1
            prev_end = reader.line_num
            if any(c.strip() for c in cells):
                rows.append([c.strip() for c in cells])
                lines.append(first_line - 1 + start)
    except csv.Error as exc:
        raise CsvParseError("Não foi possível ler o arquivo. Confira as aspas e os separadores das colunas.") from exc
    return ParsedCsv(separator=sep, rows=rows, lines=lines)


# ---------------------------------------------------------------------------------------------
# Mapeamento de colunas
# ---------------------------------------------------------------------------------------------


def _header_key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_text(header))


def auto_map_headers(headers: Sequence[str]) -> list[str]:
    """Associa cabeçalhos a campos: 1º por nome exato (sem acentos/pontuação), depois por "contém"
    (apelidos com 4+ letras). Cada campo é usado no máximo uma vez. "" = ignorar a coluna."""
    mapping = [""] * len(headers)
    used: set[str] = set()
    keys = [_header_key(h) for h in headers]

    for i, k in enumerate(keys):
        if not k:
            continue
        f = next((f for f in IMPORT_FIELDS if f.key not in used and k in f.aliases), None)
        if f:
            mapping[i] = f.key
            used.add(f.key)
    for i, k in enumerate(keys):
        if not k or mapping[i]:
            continue
        f = next((f for f in IMPORT_FIELDS if f.key not in used and any(len(a) >= 4 and a in k for a in f.aliases)), None)
        if f:
            mapping[i] = f.key
            used.add(f.key)
    return mapping


def clean_mapping(mapping, n_columns: int) -> list[str]:
    """Valida o mapeamento vindo do cliente: lista de chaves conhecidas (ou "") sem repetir campos.
    Completa/corta para o número de colunas do arquivo. Levanta ValueError se inválido."""
    if not isinstance(mapping, (list, tuple)):
        raise ValueError("Mapeamento de colunas inválido.")
    out: list[str] = []
    seen: set[str] = set()
    for item in list(mapping)[:n_columns]:
        key = item if isinstance(item, str) else ""
        if key and key not in IMPORT_FIELD_KEYS:
            raise ValueError("Mapeamento de colunas inválido.")
        if key and key in seen:
            raise ValueError(f"O campo “{IMPORT_FIELD_LABELS[key]}” foi associado a mais de uma coluna.")
        if key:
            seen.add(key)
        out.append(key)
    out.extend([""] * (n_columns - len(out)))
    return out


def missing_required_fields(mapping: Sequence[str]) -> list[str]:
    return [f.key for f in IMPORT_FIELDS if f.required and f.key not in mapping]


@dataclass
class ImportRecord:
    row: int  # linha no arquivo original (1 = primeira)
    values: dict[str, str]


def build_import_records(parsed: ParsedCsv, mapping: Sequence[str], has_header: bool) -> list[ImportRecord]:
    """Converte as linhas do CSV em registros {campo: valor} conforme o mapeamento."""
    out: list[ImportRecord] = []
    for idx, cells in enumerate(parsed.rows):
        if has_header and idx == 0:
            continue
        values: dict[str, str] = {}
        for col, key in enumerate(mapping):
            if not key:
                continue
            v = (cells[col] if col < len(cells) else "").strip()
            if v:
                values[key] = v
        out.append(ImportRecord(row=parsed.lines[idx] if idx < len(parsed.lines) else idx + 1, values=values))
    return out


# ---------------------------------------------------------------------------------------------
# Validação de cada linha
# ---------------------------------------------------------------------------------------------

_GENDER_ALIASES = {
    "m": Gender.M, "masc": Gender.M, "masculino": Gender.M, "homem": Gender.M,
    "f": Gender.F, "fem": Gender.F, "feminino": Gender.F, "mulher": Gender.F,
    "o": Gender.O, "outro": Gender.O, "outros": Gender.O, "naobinario": Gender.O,
    "n": Gender.N, "ni": Gender.N, "naoinformado": Gender.N, "naoinformar": Gender.N,
    "prefereinaoinformar": Gender.N, "preferenaoinformar": Gender.N, "prefironaoinformar": Gender.N,
}  # fmt: skip

_SUPPORT_ALIASES = {
    "apoiadora": SupportLevel.APOIADOR, "apoiadores": SupportLevel.APOIADOR, "apoia": SupportLevel.APOIADOR,
    "simpatizantes": SupportLevel.SIMPATIZANTE, "simpatica": SupportLevel.SIMPATIZANTE,
    "simpatico": SupportLevel.SIMPATIZANTE,
    "indecisa": SupportLevel.INDECISO, "indecisos": SupportLevel.INDECISO, "neutro": SupportLevel.INDECISO,
    "neutra": SupportLevel.INDECISO,
    "opositora": SupportLevel.OPOSITOR, "opositores": SupportLevel.OPOSITOR, "contra": SupportLevel.OPOSITOR,
}  # fmt: skip

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def normalize_gender_input(value: str) -> str | None:
    v = (value or "").strip()
    if v.upper() in Gender.values:
        return v.upper()
    g = _GENDER_ALIASES.get(_header_key(v))
    return g.value if g else None


def normalize_support_input(value: str) -> str | None:
    k = _header_key(value)
    for level in SupportLevel:
        if _header_key(level.value) == k:
            return level.value
    s = _SUPPORT_ALIASES.get(k)
    return s.value if s else None


@dataclass
class ImportValidation:
    voter: dict | None  # None quando a linha é inválida (nome/telefone) e será ignorada
    errors: list[str] = field(default_factory=list)  # motivos que impedem a importação da linha
    warnings: list[str] = field(default_factory=list)  # opcionais inválidos: descartados, a linha é importada


def _limited(value: str | None, max_len: int) -> str:
    return collapse_spaces(value)[:max_len]


def validate_import_record(values: dict[str, str], today: date | None = None) -> ImportValidation:
    """Valida e normaliza uma linha. Nome e telefone inválidos descartam a linha; os demais campos inválidos
    viram aviso (o valor é ignorado). Devolve o dict com os nomes de campo do model Voter."""
    today = today or timezone.localdate()
    errors: list[str] = []
    warnings: list[str] = []

    raw_name = collapse_spaces(values.get("nome"))
    if len(raw_name) < 3 or not has_letter(raw_name):
        errors.append("Nome ausente ou muito curto")
    elif len(raw_name) > 120:
        errors.append("Nome com mais de 120 caracteres")

    raw_phone = (values.get("telefone") or "").strip()
    phone = normalize_br_phone(raw_phone)
    if not raw_phone:
        errors.append("Telefone ausente")
    elif phone is None:
        errors.append("Telefone inválido (use DDD + número)")

    email = ""
    if (values.get("email") or "").strip():
        e = values["email"].strip().lower()
        if _EMAIL_RE.match(e) and len(e) <= 160:
            email = e
        else:
            warnings.append("E-mail inválido (ignorado)")

    birth_date = None
    if (values.get("nascimento") or "").strip():
        d = parse_birth_date_input(values["nascimento"])
        if d is None:
            warnings.append("Data de nascimento inválida (ignorada)")
        elif not is_voter_age(age_from(d, today)):
            warnings.append(f"Idade fora do intervalo de {MIN_VOTER_AGE} a {MAX_VOTER_AGE} anos (data ignorada)")
        else:
            birth_date = d

    gender = ""
    if (values.get("genero") or "").strip():
        gender = normalize_gender_input(values["genero"]) or ""
        if not gender:
            warnings.append("Gênero não reconhecido (ignorado)")

    cep = ""
    if (values.get("cep") or "").strip():
        cep = normalize_cep(values["cep"]) or ""
        if not cep:
            warnings.append("CEP inválido (ignorado)")

    state = ""
    if (values.get("uf") or "").strip():
        uf = values["uf"].strip().upper()
        if uf in UFS:
            state = uf
        else:
            warnings.append("UF inválida (ignorada)")

    zone = section = ""
    if (values.get("zona") or "").strip():
        zone = normalize_digits_field(values["zona"], 4) or ""
        if not zone:
            warnings.append("Zona eleitoral inválida (ignorada)")
    if (values.get("secao") or "").strip():
        section = normalize_digits_field(values["secao"], 5) or ""
        if not section:
            warnings.append("Seção eleitoral inválida (ignorada)")

    support_level = ""
    if (values.get("apoio") or "").strip():
        support_level = normalize_support_input(values["apoio"]) or ""
        if not support_level:
            warnings.append("Nível de apoio não reconhecido (ignorado)")

    if errors:
        return ImportValidation(voter=None, errors=errors, warnings=warnings)

    tags_raw = re.sub(r"[|;]", ",", values.get("tags") or "")[:300]
    return ImportValidation(
        voter={
            "name": title_case(raw_name),
            "phone": phone,
            "email": email,
            "birth_date": birth_date,
            "gender": gender,
            "cep": cep,
            "street": smart_case(_limited(values.get("rua"), 160)),
            "number": _limited(values.get("numero"), 20),
            "complement": _limited(values.get("complemento"), 100),
            "neighborhood": smart_case(_limited(values.get("bairro"), 100)),
            "city": smart_case(_limited(values.get("cidade"), 100)),
            "state": state,
            "electoral_zone": zone,
            "electoral_section": section,
            "support_level": support_level,
            "tags": serialize_tags(tags_raw) or "",
        },
        errors=errors,
        warnings=warnings,
    )


@dataclass
class RowResult:
    row: int
    voter: dict | None
    errors: list[str]
    warnings: list[str]


def validate_records(records: Sequence[ImportRecord], today: date | None = None) -> list[RowResult]:
    today = today or timezone.localdate()
    results = []
    for rec in records:
        v = validate_import_record(rec.values, today)
        results.append(RowResult(row=rec.row, voter=v.voter, errors=v.errors, warnings=v.warnings))
    return results


def split_file_duplicates(results: Sequence[RowResult]) -> tuple[list[RowResult], list[RowResult]]:
    """Telefones repetidos no próprio arquivo: vale a primeira ocorrência. Devolve (únicos, repetidos);
    linhas inválidas (voter None) ficam de fora dos dois grupos."""
    seen: set[str] = set()
    unique: list[RowResult] = []
    repeated: list[RowResult] = []
    for r in results:
        if r.voter is None:
            continue
        phone = r.voter["phone"]
        if phone in seen:
            repeated.append(r)
        else:
            seen.add(phone)
            unique.append(r)
    return unique, repeated


SAMPLE_COLUMNS = ["nome", "telefone", "email", "nascimento", "genero", "cep", "rua", "numero", "complemento",
                  "bairro", "cidade", "uf", "zona", "secao", "apoio", "tags"]  # fmt: skip


# --- Modelo para download (/painel/apoiadores/importar/modelo/) e guia de preenchimento -------------------------
# As linhas de exemplo usam telefone INVÁLIDO de propósito (DDD 00): se alguém esquecer de apagá-las, o importador as
# rejeita em vez de cadastrar apoiadores fictícios.
TEMPLATE_EXAMPLE_ROWS = [
    ["EXEMPLO - apague esta linha", "(00) 90000-0000", "maria@exemplo.com", "15/03/1985", "Feminino", "01310-100",
     "Avenida Paulista", "1000", "Apto 12", "Bela Vista", "São Paulo", "SP", "1", "25", "Apoiador", "saúde, jovem"],
    ["EXEMPLO - apague esta linha", "(00) 90000-0001", "", "", "Masculino", "", "", "", "", "Centro", "Campinas",
     "SP", "", "", "Simpatizante", ""],
]  # fmt: skip

# coluna → (formato / valores aceitos, exemplo)
_GUIDE_TEXT = {
    "nome": ("Nome completo, com pelo menos 3 letras.", "Maria da Silva"),
    "telefone": ("DDD + número, com ou sem máscara. Telefones já cadastrados na campanha são ignorados.", "(11) 98765-4321"),
    "email": ("Endereço de e-mail válido.", "maria@exemplo.com"),
    "nascimento": (f"dd/mm/aaaa ou aaaa-mm-dd. Idade entre {MIN_VOTER_AGE} e {MAX_VOTER_AGE} anos.", "15/03/1985"),
    "genero": ("Feminino, Masculino, Outro ou Prefere não informar (também aceita F, M, O, N).", "Feminino"),
    "cep": ("8 dígitos, com ou sem hífen. Usado para localizar o apoiador no mapa.", "01310-100"),
    "rua": ("Logradouro (rua, avenida...).", "Avenida Paulista"),
    "numero": ("Número do imóvel. Não é enviado a serviços externos de mapa.", "1000"),
    "complemento": ("Apartamento, bloco, referência.", "Apto 12"),
    "bairro": ("Importante para o mapa, os filtros e as regiões. Escreva o nome oficial do bairro.", "Bela Vista"),
    "cidade": ("Nome da cidade.", "São Paulo"),
    "uf": ("Sigla do estado, com 2 letras.", "SP"),
    "zona": ("Número da zona eleitoral.", "1"),
    "secao": ("Número da seção eleitoral.", "25"),
    "apoio": ("Apoiador, Simpatizante, Indeciso ou Opositor.", "Apoiador"),
    "tags": ("Várias tags separadas por vírgula.", "saúde, jovem"),
}

COLUMN_GUIDE = [
    {
        "key": f.key,
        "label": f.label,
        "required": f.required,
        "format": _GUIDE_TEXT[f.key][0],
        "example": _GUIDE_TEXT[f.key][1],
    }
    for f in IMPORT_FIELDS
]


def build_template_csv() -> str:
    """Conteúdo do modelo: cabeçalho (nomes que o importador reconhece sozinho) + 2 linhas de exemplo.
    CSV com BOM UTF-8 e ";" — abre direto no Excel/LibreOffice/Google Planilhas em português e reimporta sem ajustes."""
    columns = [(key, key) for key in SAMPLE_COLUMNS]
    rows = [dict(zip(SAMPLE_COLUMNS, row, strict=True)) for row in TEMPLATE_EXAMPLE_ROWS]
    return to_csv(rows, columns)
