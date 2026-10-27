-- The PII boundary must hold: staging may never expose the raw NIK or bank
-- account number that lives in the raw layer.
with staged as (select * from {{ ref('stg_bendahara') }}),
raw_values as (select * from {{ source('raw', 'raw_bendahara') }})

select s.id_bendahara
from staged s
join raw_values r using (id_bendahara)
where s.nik_masked = r.nik
   or s.no_rekening_masked = r.no_rekening
   or s.nik_hash <> encode(sha256(convert_to(r.nik, 'UTF8')), 'hex')
