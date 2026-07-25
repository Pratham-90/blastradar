with base as (
    select
        customer_id,
        signup_date
    from raw.customers
)

select * from base
