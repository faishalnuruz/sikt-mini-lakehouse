-- Fact table, grain: one row per SKPD x account x month.
-- Realization only: the pagu is a budget attribute, not a monthly fact, and
-- joining it here would repeat it once per month and triple the budget.
select
    kode_skpd,
    kode_akun,
    bulan,
    sum(jumlah) as realisasi
from {{ ref('stg_simda_bku') }}
where jenis = 'PENGELUARAN'
group by 1, 2, 3
