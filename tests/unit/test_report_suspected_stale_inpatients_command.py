from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
def test_reports_only_active_admissions_without_events_in_last_72h(tmp_path: Path):
    now = timezone.now()

    # Paciente ativo com evolução antiga (>72h) na admissão → entra
    p_stale = Patient.objects.create(
        patient_source_key="P1", source_system="tasy", name="Paciente Stale"
    )
    a_stale = Admission.objects.create(
        patient=p_stale,
        source_admission_key="A1",
        source_system="tasy",
        admission_date=now - timedelta(days=10),
        discharge_date=None,
        ward="Clinica",
        bed="101A",
        source_patient_reference="P1",
    )
    ClinicalEvent.objects.create(
        admission=a_stale,
        patient=p_stale,
        event_identity_key="evt-1",
        content_hash="h1",
        happened_at=now - timedelta(hours=80),
        author_name="Autor",
        profession_type="enfermagem",
        content_text="texto",
        raw_payload_json={},
    )

    # Paciente ativo com evolução recente (<72h) na admissão → NÃO entra
    p_recent = Patient.objects.create(
        patient_source_key="P2", source_system="tasy", name="Paciente Recente"
    )
    a_recent = Admission.objects.create(
        patient=p_recent,
        source_admission_key="A2",
        source_system="tasy",
        admission_date=now - timedelta(days=3),
        discharge_date=None,
        ward="UTI",
        bed="201B",
        source_patient_reference="P2",
    )
    ClinicalEvent.objects.create(
        admission=a_recent,
        patient=p_recent,
        event_identity_key="evt-2",
        content_hash="h2",
        happened_at=now - timedelta(hours=12),
        author_name="Autor",
        profession_type="medica",
        content_text="texto",
        raw_payload_json={},
    )

    # Paciente com alta (discharge_date preenchida) → NÃO entra
    p_discharged = Patient.objects.create(
        patient_source_key="P3", source_system="tasy", name="Paciente Alta"
    )
    a_discharged = Admission.objects.create(
        patient=p_discharged,
        source_admission_key="A3",
        source_system="tasy",
        admission_date=now - timedelta(days=6),
        discharge_date=now - timedelta(days=1),
        ward="Enfermaria",
        bed="301C",
        source_patient_reference="P3",
    )
    ClinicalEvent.objects.create(
        admission=a_discharged,
        patient=p_discharged,
        event_identity_key="evt-3",
        content_hash="h3",
        happened_at=now - timedelta(hours=120),
        author_name="Autor",
        profession_type="fisioterapia",
        content_text="texto",
        raw_payload_json={},
    )

    # Paciente ativo sem nenhuma evolução na admissão → entra
    p_never = Patient.objects.create(
        patient_source_key="P4", source_system="tasy", name="Paciente Sem Evolucao"
    )
    Admission.objects.create(
        patient=p_never,
        source_admission_key="A4",
        source_system="tasy",
        admission_date=now - timedelta(days=1),
        discharge_date=None,
        ward="Observacao",
        bed="",
        source_patient_reference="P4",
    )

    output = tmp_path / "suspeitos.csv"
    call_command("report_suspected_stale_inpatients", "--output", str(output))

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    prontuarios = {r["prontuario"] for r in rows}
    assert prontuarios == {"P1", "P4"}


@pytest.mark.django_db
def test_deduplicates_patient_with_multiple_stale_admissions(tmp_path: Path):
    """Paciente com 2 admissões ativas sem evento aparece apenas uma vez."""
    now = timezone.now()

    p = Patient.objects.create(
        patient_source_key="P5", source_system="tasy", name="Paciente Duplo"
    )
    Admission.objects.create(
        patient=p,
        source_admission_key="A5a",
        source_system="tasy",
        admission_date=now - timedelta(days=10),
        discharge_date=None,
        ward="Clinica",
        bed="101A",
        source_patient_reference="P5",
    )
    Admission.objects.create(
        patient=p,
        source_admission_key="A5b",
        source_system="tasy",
        admission_date=now - timedelta(days=5),
        discharge_date=None,
        ward="UTI",
        bed="201B",
        source_patient_reference="P5",
    )

    output = tmp_path / "suspeitos.csv"
    call_command("report_suspected_stale_inpatients", "--output", str(output))

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    prontuarios = [r["prontuario"] for r in rows]
    assert prontuarios.count("P5") == 1


@pytest.mark.django_db
def test_excludes_patient_whose_latest_admission_has_discharge(tmp_path: Path):
    """Paciente com admissão antiga (sem alta) e admissão recente (com alta)
       NÃO deve aparecer no relatório — a admissão mais recente tem alta."""
    now = timezone.now()

    p = Patient.objects.create(
        patient_source_key="P6", source_system="tasy", name="Paciente Alta Recente"
    )
    # Admissão antiga sem alta (resíduo de dados)
    Admission.objects.create(
        patient=p,
        source_admission_key="A6a",
        source_system="tasy",
        admission_date=now - timedelta(days=30),
        discharge_date=None,
        ward="Clinica",
        bed="101A",
        source_patient_reference="P6",
    )
    # Admissão recente COM alta
    Admission.objects.create(
        patient=p,
        source_admission_key="A6b",
        source_system="tasy",
        admission_date=now - timedelta(days=5),
        discharge_date=now - timedelta(days=1),
        ward="UTI",
        bed="201B",
        source_patient_reference="P6",
    )

    output = tmp_path / "suspeitos.csv"
    call_command("report_suspected_stale_inpatients", "--output", str(output))

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    prontuarios = {r["prontuario"] for r in rows}
    assert "P6" not in prontuarios


@pytest.mark.django_db
def test_census_filter_excludes_patients_in_census_by_default(tmp_path: Path):
    """Por padrão, pacientes que ainda aparecem no último censo como
       ocupados NÃO são listados — apenas os que sumiram do censo."""
    now = timezone.now()

    # Paciente que NÃO está no censo → entra
    p_not_in_census = Patient.objects.create(
        patient_source_key="P7", source_system="tasy",
        name="Paciente Fora do Censo"
    )
    Admission.objects.create(
        patient=p_not_in_census,
        source_admission_key="A7",
        source_system="tasy",
        admission_date=now - timedelta(days=10),
        discharge_date=None,
        ward="Clinica", bed="101A",
        source_patient_reference="P7",
    )

    # Paciente que ESTÁ no censo → NÃO entra (por padrão)
    p_in_census = Patient.objects.create(
        patient_source_key="P8", source_system="tasy",
        name="Paciente No Censo"
    )
    Admission.objects.create(
        patient=p_in_census,
        source_admission_key="A8",
        source_system="tasy",
        admission_date=now - timedelta(days=5),
        discharge_date=None,
        ward="UTI", bed="201B",
        source_patient_reference="P8",
    )

    CensusSnapshot.objects.create(
        captured_at=now,
        setor="Clinica", leito="101B",
        prontuario="P8", nome="Paciente No Censo",
        especialidade="CME", bed_status=BedStatus.OCCUPIED,
    )

    output = tmp_path / "suspeitos.csv"
    call_command("report_suspected_stale_inpatients", "--output", str(output))

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    prontuarios = {r["prontuario"] for r in rows}
    assert "P7" in prontuarios
    assert "P8" not in prontuarios


@pytest.mark.django_db
def test_include_census_present_flag_shows_census_patients(tmp_path: Path):
    """Com --include-census-present, pacientes no censo também aparecem."""
    now = timezone.now()

    p = Patient.objects.create(
        patient_source_key="P9", source_system="tasy",
        name="Paciente Censo Incluido"
    )
    Admission.objects.create(
        patient=p,
        source_admission_key="A9",
        source_system="tasy",
        admission_date=now - timedelta(days=5),
        discharge_date=None,
        ward="UTI", bed="201B",
        source_patient_reference="P9",
    )

    CensusSnapshot.objects.create(
        captured_at=now,
        setor="UTI", leito="201B",
        prontuario="P9", nome="Paciente Censo Incluido",
        especialidade="CME", bed_status=BedStatus.OCCUPIED,
    )

    output = tmp_path / "suspeitos.csv"
    call_command(
        "report_suspected_stale_inpatients",
        "--output", str(output),
        "--include-census-present",
    )

    with output.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    prontuarios = {r["prontuario"] for r in rows}
    assert "P9" in prontuarios


@pytest.mark.django_db
def test_refresh_suspected_admissions_enqueues_runs(tmp_path: Path):
    """refresh_suspected_admissions lê o CSV e enfileira admissions_only runs."""
    import csv

    # Prepara CSV de entrada
    input_csv = tmp_path / "samples.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["nome", "prontuario", "setor", "leito",
                        "especialidade", "esta_no_censo",
                        "ultima_evolucao_em", "horas_desde_ultima_evolucao",
                        "profissao_ultima_evolucao", "status_suspeita"],
        )
        writer.writeheader()
        writer.writerow({
            "nome": "Paciente A", "prontuario": "PR-A",
            "setor": "", "leito": "", "especialidade": "",
            "esta_no_censo": "não", "ultima_evolucao_em": "",
            "horas_desde_ultima_evolucao": "",
            "profissao_ultima_evolucao": "",
            "status_suspeita": "SEM_EVOLUCAO_72H",
        })
        writer.writerow({
            "nome": "Paciente B", "prontuario": "PR-B",
            "setor": "", "leito": "", "especialidade": "",
            "esta_no_censo": "não", "ultima_evolucao_em": "",
            "horas_desde_ultima_evolucao": "",
            "profissao_ultima_evolucao": "",
            "status_suspeita": "STALE_72H",
        })
        # Linha duplicada — deve ser deduplicada
        writer.writerow({
            "nome": "Paciente A", "prontuario": "PR-A",
            "setor": "", "leito": "", "especialidade": "",
            "esta_no_censo": "não", "ultima_evolucao_em": "",
            "horas_desde_ultima_evolucao": "",
            "profissao_ultima_evolucao": "",
            "status_suspeita": "SEM_EVOLUCAO_72H",
        })

    before_count = IngestionRun.objects.count()

    call_command("refresh_suspected_admissions", "--input", str(input_csv))

    after_count = IngestionRun.objects.count()
    assert after_count == before_count + 2  # PR-A, PR-B (duplicata ignorada)

    runs = IngestionRun.objects.filter(status="queued", intent="admissions_only")
    assert runs.count() == 2
    prontuarios = {
        r.parameters_json["patient_record"] for r in runs
    }
    assert prontuarios == {"PR-A", "PR-B"}


@pytest.mark.django_db
def test_sync_missing_discharges_enqueues_only_patients_not_in_census(
    tmp_path: Path,
):
    """Paciente com admissão ativa que NÃO está no censo é enfileirado."""
    now = timezone.now()

    # Paciente fora do censo → enfileirado
    p = Patient.objects.create(
        patient_source_key="P10", source_system="tasy",
        name="Fora do Censo"
    )
    Admission.objects.create(
        patient=p,
        source_admission_key="A10",
        source_system="tasy",
        admission_date=now - timedelta(days=3),
        discharge_date=None,
        ward="Clinica", bed="101A",
        source_patient_reference="P10",
    )

    # Paciente no censo → NÃO enfileirado
    p2 = Patient.objects.create(
        patient_source_key="P11", source_system="tasy",
        name="No Censo"
    )
    Admission.objects.create(
        patient=p2,
        source_admission_key="A11",
        source_system="tasy",
        admission_date=now - timedelta(days=2),
        discharge_date=None,
        ward="UTI", bed="201B",
        source_patient_reference="P11",
    )

    CensusSnapshot.objects.create(
        captured_at=now,
        setor="UTI", leito="201B",
        prontuario="P11", nome="No Censo",
        especialidade="CME", bed_status=BedStatus.OCCUPIED,
    )

    call_command("sync_missing_discharges")

    runs = IngestionRun.objects.filter(status="queued", intent="admissions_only")
    prontuarios = {r.parameters_json["patient_record"] for r in runs}
    assert prontuarios == {"P10"}


@pytest.mark.django_db
def test_sync_missing_discharges_skips_discharged_patients():
    """Paciente com admissão mais recente COM alta NÃO é enfileirado."""
    now = timezone.now()

    p = Patient.objects.create(
        patient_source_key="P12", source_system="tasy",
        name="Ja Teve Alta"
    )
    Admission.objects.create(
        patient=p,
        source_admission_key="A12",
        source_system="tasy",
        admission_date=now - timedelta(days=3),
        discharge_date=now - timedelta(days=1),
        ward="Clinica", bed="101A",
        source_patient_reference="P12",
    )

    call_command("sync_missing_discharges")

    runs = IngestionRun.objects.filter(status="queued", intent="admissions_only")
    prontuarios = {r.parameters_json["patient_record"] for r in runs}
    assert "P12" not in prontuarios


@pytest.mark.django_db
def test_sync_missing_discharges_dry_run_lists_without_enqueuing():
    """Dry-run lista pacientes mas não cria runs."""
    now = timezone.now()

    p = Patient.objects.create(
        patient_source_key="P13", source_system="tasy",
        name="Dry Run Test"
    )
    Admission.objects.create(
        patient=p,
        source_admission_key="A13",
        source_system="tasy",
        admission_date=now - timedelta(days=3),
        discharge_date=None,
        ward="Clinica", bed="101A",
        source_patient_reference="P13",
    )

    before = IngestionRun.objects.count()
    call_command("sync_missing_discharges", "--dry-run")
    after = IngestionRun.objects.count()
    assert after == before  # Nenhuma run criada


@pytest.mark.django_db
def test_refresh_suspected_admissions_handles_empty_csv(tmp_path: Path):
    """CSV vazio não gera erro nem cria runs."""
    import csv

    input_csv = tmp_path / "empty.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["nome", "prontuario"],
        )
        writer.writeheader()

    before_count = IngestionRun.objects.count()
    call_command("refresh_suspected_admissions", "--input", str(input_csv))
    assert IngestionRun.objects.count() == before_count
