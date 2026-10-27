-- Legacy Oracle Aset: the one source that arrives as a nightly file drop.
with source as (select * from {{ source('raw', 'raw_aset') }})

select
    trim(kode_barang)               as kode_barang,
    nama_barang,
    cast(tahun_perolehan as integer) as tahun_perolehan,
    trim(kode_skpd)                 as kode_skpd,
    trim(kode_akun)                 as kode_akun,
    cast(nilai_aset as numeric(15, 2)) as nilai_aset
from source
