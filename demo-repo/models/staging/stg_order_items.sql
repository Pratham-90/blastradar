-- Staging: order line items.
with source as (

    select * from order_entry.order_items

),

renamed as (

    select
        order_id,
        line_item_id,
        product_id,
        quantity,
        unit_price,
        dispatch_date
    from source

)

select * from renamed
