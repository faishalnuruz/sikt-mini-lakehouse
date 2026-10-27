-- One row per BKU entry, typed and trimmed. Realization is measured from here.
with source as (select * from {{ source('raw', 'raw_bku') }})

select
    cast(id_bku as bigint)                 as id_bku,
    trim(kode_skpd)                        as kode_skpd,
    cast(tanggal as date)                  as tanggal,
    date_trunc('month', cast(tanggal as date)) as bulan,
    trim(kode_akun)                        as kode_akun,
    uraian,
    cast(jumlah as numeric(15, 2))          as jumlah,
    upper(jenis)                           as jenis,
    cast(id_bendahara as integer)          as id_bendahara,
    cast(_loaded_at as timestamp)           as loaded_at
from source
