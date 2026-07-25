-- Staging: orders, typed and trimmed to the columns marts need.
with source as (

    select * from order_entry.orders

),

renamed as (

    select
        order_id,
        customer_id,
        order_date,
        order_status,
        order_total,
        order_mode
    from source

)

select * from renamed
