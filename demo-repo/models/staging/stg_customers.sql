-- Staging: light cleanup + renames over the raw customers table.
-- (Compiled form shown; the authored model uses {{ source('order_entry','customers') }}.)
with source as (

    select * from order_entry.customers

),

renamed as (

    select
        customer_id,
        cust_first_name   as first_name,
        cust_last_name    as last_name,
        cust_email        as email,
        customer_since,
        customer_class    as loyalty_tier,
        credit_limit,
        phone_number,
        town_city,
        country_id
    from source

)

select * from renamed
