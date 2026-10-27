-- FR7 boundary: NIK and bank account numbers are hashed here and never leave
-- the raw schema. Downstream models see a SHA-256 fingerprint (for joins) and
-- a display mask — never the raw values.
with source as (select * from {{ source('raw', 'raw_bendahara') }})

select
    cast(id_bendahara as integer) as id_bendahara,
    trim(kode_skpd)                as kode_skpd,
    nama,
    encode(sha256(convert_to(nik, 'UTF8')), 'hex')          as nik_hash,
    '****' || right(nik, 4)                                 as nik_masked,
    encode(sha256(convert_to(no_rekening, 'UTF8')), 'hex') as no_rekening_hash,
    '****' || right(no_rekening, 4)                         as no_rekening_masked
from source
