import csv
from dataclasses import asdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO, TextIOWrapper

from openpyxl import load_workbook

from .models import Participant


REQUIRED_PARTICIPANT_COLUMNS = ["first_name", "last_name"]
PARTICIPANT_COLUMNS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "status",
    "is_child",
    "is_youth_group",
    "is_companion",
    "booked_nights",
    "actual_nights",
    "notes",
]


@dataclass
class ImportRow:
    row_number: int
    data: dict
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self):
        return not self.errors


def parse_bool(value):
    if value in (True, False):
        return bool(value)
    if value is None or value == "":
        return False
    return str(value).strip().lower() in {"1", "true", "ja", "yes", "x"}


def parse_int(value, field_name, errors):
    if value in (None, ""):
        return 0
    try:
        return int(Decimal(str(value).replace(",", ".")))
    except (InvalidOperation, ValueError):
        errors.append(f"{field_name}: keine gültige Zahl")
        return 0


def normalize_row(raw, row_number):
    errors = []
    data = {column: raw.get(column, "") for column in PARTICIPANT_COLUMNS}
    for column in REQUIRED_PARTICIPANT_COLUMNS:
        if not str(data.get(column, "")).strip():
            errors.append(f"{column}: Pflichtfeld fehlt")
    for column in ["booked_nights", "actual_nights"]:
        data[column] = parse_int(data.get(column), column, errors)
    for column in ["is_child", "is_youth_group", "is_companion"]:
        data[column] = parse_bool(data.get(column))
    return ImportRow(row_number=row_number, data=data, errors=errors)


def read_csv(file_obj):
    wrapper = TextIOWrapper(file_obj, encoding="utf-8-sig")
    reader = csv.DictReader(wrapper)
    return [normalize_row(row, index) for index, row in enumerate(reader, start=2)]


def read_xlsx(file_obj):
    workbook = load_workbook(BytesIO(file_obj.read()), read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    parsed = []
    for index, values in enumerate(rows[1:], start=2):
        raw = dict(zip(headers, values, strict=False))
        parsed.append(normalize_row(raw, index))
    return parsed


def preview_participants(file_obj, filename):
    if filename.lower().endswith(".xlsx"):
        return read_xlsx(file_obj)
    return read_csv(file_obj)


def rows_to_payload(rows):
    return [asdict(row) for row in rows]


def rows_from_payload(payload):
    return [ImportRow(row_number=row["row_number"], data=row["data"], errors=row.get("errors", [])) for row in payload]


def save_participants(camp, rows):
    created = []
    for row in rows:
        if not row.valid:
            continue
        participant, _ = Participant.objects.update_or_create(
            camp=camp,
            first_name=row.data["first_name"],
            last_name=row.data["last_name"],
            defaults={field: row.data[field] for field in PARTICIPANT_COLUMNS if field not in {"first_name", "last_name"}},
        )
        created.append(participant)
    return created
