from __future__ import annotations

from apps.census.models import BedStatus
from apps.census.services import classify_bed_status


class TestClassifyBedStatus:
    def test_occupied_with_prontuario(self):
        assert (
            classify_bed_status("14160147", "JOSE AUGUSTO MERCES")
            == BedStatus.OCCUPIED
        )

    def test_occupied_even_with_weird_name(self):
        """Se tem prontuario, é occupied independente do nome."""
        assert (
            classify_bed_status("99999", "IGNORADO SUPOSTO CLAUDIO")
            == BedStatus.OCCUPIED
        )

    def test_empty_desocupado(self):
        assert classify_bed_status("", "DESOCUPADO") == BedStatus.EMPTY

    def test_empty_vazio(self):
        assert classify_bed_status("", "VAZIO") == BedStatus.EMPTY

    def test_empty_case_insensitive(self):
        assert classify_bed_status("", "desocupado") == BedStatus.EMPTY

    def test_maintenance_limpeza(self):
        assert classify_bed_status("", "LIMPEZA") == BedStatus.MAINTENANCE

    def test_reserved_reserva_interna(self):
        assert (
            classify_bed_status("", "RESERVA INTERNA") == BedStatus.RESERVED
        )

    def test_reserved_reserva_cirurgica(self):
        assert (
            classify_bed_status("", "RESERVA CIRÚRGICA") == BedStatus.RESERVED
        )

    def test_reserved_reserva_regulacao(self):
        assert (
            classify_bed_status("", "RESERVA REGULAÇÃO") == BedStatus.RESERVED
        )

    def test_reserved_reserva_hemodinamica(self):
        assert (
            classify_bed_status("", "RESERVA HEMODINÂMICA") == BedStatus.RESERVED
        )

    def test_isolation_isolamento_medico(self):
        assert (
            classify_bed_status("", "ISOLAMENTO MÉDICO") == BedStatus.ISOLATION
        )

    def test_isolation_isolamento_social(self):
        assert (
            classify_bed_status("", "ISOLAMENTO SOCIAL") == BedStatus.ISOLATION
        )

    def test_fallback_unknown_empty(self):
        """Nome desconhecido sem prontuario → empty."""
        assert (
            classify_bed_status("", "ALGUMA COISA ESTRANHA") == BedStatus.EMPTY
        )

    def test_prontuario_with_spaces(self):
        """Prontuario com espaços em branco → occupied."""
        assert classify_bed_status(" 14160147 ", "JOSE") == BedStatus.OCCUPIED

    def test_empty_prontuario_empty_string(self):
        """Prontuario vazio com string vazia."""
        assert classify_bed_status("", "") == BedStatus.EMPTY
