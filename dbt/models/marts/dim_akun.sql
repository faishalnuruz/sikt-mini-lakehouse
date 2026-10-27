-- One row per expenditure account seen in either the ledger or the budget.
select kode_akun
from (
    select distinct kode_akun from {{ ref('stg_simda_bku') }}
    union
    select distinct kode_akun from {{ ref('stg_pagu') }}
) accounts
where kode_akun is not null
