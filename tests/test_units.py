"""Unit tests for the CDC parsers and payload builders — no stack needed."""

from decimal import Decimal
from typing import ClassVar

from sikt import targets
from sikt.alert_realisasi import build_payload
from sikt.cdc_pg import parse_line
from sikt.landing import object_key


class TestTestDecodingParser:
    def test_insert_with_quoted_and_plain_values(self):
        record = parse_line(
            "table public.pagu_anggaran: INSERT: id[integer]:1 tahun[integer]:2026 "
            "kode_skpd[character varying]:'1.05.02' pagu[numeric]:'2760000000.00' "
            "updated_at[timestamp with time zone]:'2026-10-27 11:21:44.657112'"
        )

        assert record["table"] == "pagu_anggaran"
        assert record["action"] == "insert"
        assert record["values"]["id"] == "1"
        assert record["values"]["kode_skpd"] == "1.05.02"
        assert record["values"]["pagu"] == "2760000000.00"

    def test_unquoted_values_are_not_swallowed_as_empty_strings(self):
        # Regression: findall() flattens non-participating groups to '', which
        # turned every unquoted numeric into an empty string.
        record = parse_line("table public.t: INSERT: id[integer]:7 name[text]:'x'")

        assert record["values"]["id"] == "7"

    def test_update_and_delete_actions(self):
        update = parse_line("table public.pagu_anggaran: UPDATE: id[integer]:2 pagu[numeric]:'5.0'")
        delete = parse_line("table public.pagu_anggaran: DELETE: id[integer]:2")

        assert update["action"] == "update"
        assert delete["action"] == "delete"

    def test_escaped_quotes_inside_text_values(self):
        record = parse_line("table public.t: INSERT: uraian[text]:'Bayar O''Brien'")

        assert record["values"]["uraian"] == "Bayar O'Brien"

    def test_null_values_are_preserved_as_null(self):
        record = parse_line("table public.t: INSERT: a[text]:null b[integer]:3")

        assert record["values"]["a"] is None
        assert record["values"]["b"] == "3"

    def test_noise_lines_are_ignored(self):
        assert parse_line("BEGIN 776") is None
        assert parse_line("COMMIT 776 (at 2026-10-27)") is None


class TestLandingKeys:
    def test_keys_are_partitioned_by_year_and_month(self):
        from datetime import UTC, datetime

        moment = datetime(2026, 10, 24, 8, 30, tzinfo=UTC)
        key = object_key("pg-ebudget", "changes-1.jsonl", moment)

        assert key == "pg-ebudget/year=2026/month=10/changes-1.jsonl"


class TestAlertPayload:
    ROW: ClassVar[dict] = {
        "kode_skpd": "1.05.02",
        "nama_skpd": "Dinas Sosial",
        "pagu_total": Decimal("920000000000.00"),
        "realisasi_total": Decimal("855599999999.98"),
        "sisa_pagu": Decimal("64400000000.02"),
        "persen_realisasi": Decimal("93.00"),
    }

    def test_payload_names_every_skpd_and_the_threshold(self):
        payload = build_payload([self.ROW])

        text = payload["blocks"][0]["text"]["text"]
        assert "90% pagu" in text
        section = payload["blocks"][2]["text"]["text"]
        assert "Dinas Sosial" in section
        assert "93.00" in section

    def test_amounts_are_formatted_in_rupiah(self):
        section = build_payload([self.ROW])["blocks"][2]["text"]["text"]

        assert "Rp 920.00 M" in section
        assert "Rp 855.60 M" in section

    def test_an_empty_alert_is_still_a_valid_message(self):
        payload = build_payload([])

        assert "0 SKPD" in payload["blocks"][1]["text"]["text"]


class TestScenarioInvariants:
    def test_exactly_one_skpd_starts_over_the_threshold(self):
        # The demo story needs one SKPD already over 90% from the seed data.
        assert targets.over_threshold() == ["1.05.02"]

    def test_program_codes_are_hierarchical_and_unique(self):
        all_codes = [code for programs in targets.PROGRAMS.values() for code, _ in programs]

        assert len(all_codes) == len(set(all_codes))
        for skpd, programs in targets.PROGRAMS.items():
            for code, _ in programs:
                assert code.startswith(skpd + ".")

    def test_expected_realisasi_is_a_share_of_the_pagu(self):
        for kode, _, pagu, share in targets.SKPDS:
            expected = targets.expected_realisasi(kode)

            assert 0 < expected < pagu
            assert abs(expected - pagu * share) < 0.01
