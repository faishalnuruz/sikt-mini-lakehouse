"""The scenario both seeds build, so the numbers reconcile end to end.

Five Jakarta-style SKPDs. Dinas Sosial is deliberately heading over 90% of its
pagu — that is the case the #finmon-alerts notification exists to catch, and
having exactly one over-threshold SKPD makes the demo unambiguous.
"""

from __future__ import annotations

TAHUN_ANGGARAN = 2026

# kode_skpd, nama_skpd, pagu (IDR), realized share of pagu by mid-October
SKPDS = [
    ("1.01.02", "Dinas Pendidikan", 2_150_000_000_000, 0.62),
    ("1.02.02", "Dinas Kesehatan", 1_480_000_000_000, 0.71),
    ("1.04.02", "Dinas Pekerjaan Umum dan Penataan Ruang", 2_870_000_000_000, 0.48),
    ("1.05.02", "Dinas Sosial", 920_000_000_000, 0.93),
    ("2.16.02", "Sekretariat Daerah", 640_000_000_000, 0.44),
]

ALERT_THRESHOLD = 0.90

# Program codes are hierarchical under the SKPD, as they are in the real
# APBD structure — which also makes them globally unique here.
PROGRAMS = {
    "1.01.02": [("1.01.02.01", "Program Pengelolaan Pendidikan"), ("1.01.02.02", "Program Bantuan Pendidikan")],
    "1.02.02": [("1.02.02.01", "Program Pelayanan Kesehatan"), ("1.02.02.02", "Program Promosi Kesehatan")],
    "1.04.02": [
        ("1.04.02.01", "Program Penyelenggaraan Jalan dan Jembatan"),
        ("1.04.02.02", "Program Pengendalian Sampah"),
    ],
    "1.05.02": [
        ("1.05.02.01", "Program Perlindungan dan Kesejahteraan Sosial"),
        ("1.05.02.02", "Program Penanganan Kemiskinan"),
    ],
    "2.16.02": [("2.16.02.01", "Program Administrasi Pemerintahan Daerah")],
}

# Belanja (expenditure) accounts, the ones realization is measured against.
AKUN_BELANJA = ("521111", "522151", "522211", "523213", "524114")


def pagu_for(kode_skpd: str) -> float:
    return next(entry[2] for entry in SKPDS if entry[0] == kode_skpd)


def nama_for(kode_skpd: str) -> str:
    return next(entry[1] for entry in SKPDS if entry[0] == kode_skpd)


def over_threshold() -> list[str]:
    return [kode for kode, _, _, share in SKPDS if share > ALERT_THRESHOLD]


def expected_realisasi(kode_skpd: str) -> float:
    return round(pagu_for(kode_skpd) * next(entry[3] for entry in SKPDS if entry[0] == kode_skpd), 2)
