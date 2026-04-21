import argparse
import re
from datetime import datetime
from pathlib import Path

PAGE_HEADER_RE = re.compile(r"^===== PÁGINA \d+ =====$")
PAGE_TOTAL_RE = re.compile(r"^/\s*\d+$")
PAGE_NUMBER_RE = re.compile(r"^\d+$")
EVOLUTION_DATETIME_RE = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$")
SHORT_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

DEFAULT_INPUT = Path("downloads/evolucoes-intervalo.txt")
DEFAULT_OUTPUT = Path("downloads/evolucoes-intervalo-processado.txt")
DEFAULT_SORTED_OUTPUT = Path("downloads/evolucoes-intervalo-ordenado.txt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove artefatos de paginação do TXT extraído do PDF e recompõe as evoluções."
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        default=str(DEFAULT_INPUT),
        help=f"Arquivo TXT de entrada. Padrão: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=str(DEFAULT_OUTPUT),
        help=f"Arquivo TXT processado de saída. Padrão: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "sorted_output_path",
        nargs="?",
        default=str(DEFAULT_SORTED_OUTPUT),
        help=f"Arquivo TXT ordenado cronologicamente. Padrão: {DEFAULT_SORTED_OUTPUT}",
    )
    return parser.parse_args()


def remove_page_artifacts(text: str) -> list[str]:
    lines = text.splitlines()
    cleaned: list[str] = []
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()

        if PAGE_HEADER_RE.match(stripped):
            i += 1
            if i < len(lines) and PAGE_TOTAL_RE.match(lines[i].strip()):
                i += 1
            if i < len(lines) and PAGE_NUMBER_RE.match(lines[i].strip()):
                i += 1
            if i < len(lines) and lines[i].strip() == "EVOLUÇÃO":
                i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue

        if stripped == "EVOLUÇÃO" and i + 1 < len(lines) and lines[i + 1].strip() == "Identificação":
            i += 2
            while i < len(lines):
                current = lines[i].strip()
                i += 1
                if current.startswith("Código:"):
                    while i < len(lines) and not lines[i].strip():
                        i += 1
                    break
            continue

        if SHORT_TIME_RE.match(stripped):
            previous_line = cleaned[-1].strip() if cleaned else ""
            next_nonblank = peek_next_nonblank(lines, i + 1)
            if previous_line.startswith("Elaborado e assinado por"):
                i += 1
                continue
            if next_nonblank and EVOLUTION_DATETIME_RE.match(next_nonblank):
                i += 1
                continue

        cleaned.append(stripped)
        i += 1

    return cleaned


def peek_next_nonblank(lines: list[str], start_index: int) -> str | None:
    for index in range(start_index, len(lines)):
        candidate = lines[index].strip()
        if candidate:
            return candidate
    return None


def split_into_evolutions(lines: list[str]) -> list[list[str]]:
    evolutions: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if EVOLUTION_DATETIME_RE.match(line):
            if current:
                evolutions.append(trim_blank_edges(current))
                current = []
        if line or current:
            current.append(line)

    if current:
        evolutions.append(trim_blank_edges(current))

    return [evolution for evolution in evolutions if evolution]


def trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)

    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1

    return lines[start:end]


def normalize_evolution(lines: list[str]) -> str:
    normalized: list[str] = []
    previous_blank = False

    for line in lines:
        if not line:
            if not previous_blank:
                normalized.append("")
            previous_blank = True
            continue

        normalized.append(line)
        previous_blank = False

    return "\n".join(normalized).strip()


def build_output(evolutions: list[list[str]]) -> str:
    blocks: list[str] = []

    for index, evolution_lines in enumerate(evolutions, start=1):
        header = f"===== EVOLUÇÃO {index} ====="
        body = normalize_evolution(evolution_lines)
        blocks.append(f"{header}\n{body}")

    return "\n\n".join(blocks).strip() + "\n"


def sort_evolutions_chronologically(evolutions: list[list[str]]) -> list[list[str]]:
    return sorted(evolutions, key=extract_evolution_datetime)


def extract_evolution_datetime(evolution_lines: list[str]) -> datetime:
    for line in evolution_lines:
        stripped = line.strip()
        if EVOLUTION_DATETIME_RE.match(stripped):
            return datetime.strptime(stripped, "%d/%m/%Y %H:%M:%S")

    raise RuntimeError("Não foi possível localizar a data/hora inicial de uma evolução.")


def process_file(
    input_path: Path,
    output_path: Path,
    sorted_output_path: Path,
) -> tuple[int, int]:
    raw_text = input_path.read_text(encoding="utf-8")
    cleaned_lines = remove_page_artifacts(raw_text)
    evolutions = split_into_evolutions(cleaned_lines)
    sorted_evolutions = sort_evolutions_chronologically(evolutions)

    output_text = build_output(evolutions)
    sorted_output_text = build_output(sorted_evolutions)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_text, encoding="utf-8")

    sorted_output_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_output_path.write_text(sorted_output_text, encoding="utf-8")

    return len(cleaned_lines), len(evolutions)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    output_path = Path(args.output_path)
    sorted_output_path = Path(args.sorted_output_path)

    if not input_path.exists():
        raise SystemExit(f"Arquivo de entrada não encontrado: {input_path}")

    cleaned_line_count, evolution_count = process_file(
        input_path,
        output_path,
        sorted_output_path,
    )
    print(f"Arquivo processado salvo em: {output_path}")
    print(f"Arquivo ordenado salvo em: {sorted_output_path}")
    print(f"Linhas após limpeza: {cleaned_line_count}")
    print(f"Evoluções identificadas: {evolution_count}")


if __name__ == "__main__":
    main()
