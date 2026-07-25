-- Orders fact: one row per order, joined to line-item rollups.
-- Materialized as ORDER_ENTRY_DB.analytics.orders.
with orders as (

    select * from stg_orders

),

item_rollup as (

    select
        order_id,
        sum(quantity)               as item_count,
        sum(quantity * unit_price)  as gross_amount
    from stg_order_items
    group by 1

)

select
    o.order_id,
    o.customer_id,
    o.order_date,
    o.order_status,
    o.order_total,
    i.item_count,
    i.gross_amount
from orders o
left join item_rollup i
    on o.order_id = i.order_id
