-- Realization per SKPD, account, and month: the PENGELUARAN side of the BKU.
-- PENERIMAAN rows are excluded here, so the alert denominator stays honest.
select
    kode_skpd,
    kode_akun,
    bulan,
    sum(jumlah) as realisasi
from {{ ref('stg_simda_bku') }}
where jenis = 'PENGELUARAN'
group by 1, 2, 3
