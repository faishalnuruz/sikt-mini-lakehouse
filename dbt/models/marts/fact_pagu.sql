-- The budget side, grain: one row per SKPD x program x account.
-- Kept separate from fact_realisasi so a date range never multiplies the pagu.
select
    kode_skpd,
    kode_program,
    kode_akun,
    pagu
from {{ ref('stg_pagu') }}
