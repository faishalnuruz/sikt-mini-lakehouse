-- e-budgeting pagu (budget ceiling), typed from the replication slot's values.
with source as (select * from {{ source('raw', 'raw_pagu') }})

select
    cast(id as integer)           as pagu_id,
    cast(tahun as integer)        as tahun,
    trim(kode_skpd)                as kode_skpd,
    trim(kode_program)             as kode_program,
    trim(kode_akun)                as kode_akun,
    cast(pagu as numeric(15, 2))   as pagu,
    cast(updated_at as timestamp) as updated_at
from source
