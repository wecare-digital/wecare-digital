"""Durable Wix/internal order association, independent of mutable CRM contact IDs."""
import time


def bind_wix_order(orders, keys, *, order_id, order_number, wix_order_id):
    if not all(isinstance(v, str) and v for v in (order_id, order_number, wix_order_id)):
        raise ValueError('complete order association required')
    # Each conditional is replayable after a partial failure. Never replace another binding.
    keys.update_item(
        Key={'orderId': wix_order_id},
        UpdateExpression='SET orderIdRef=:id, orderNumber=:number, wixOrderId=:wix',
        ConditionExpression='(attribute_not_exists(orderIdRef) OR orderIdRef=:id) AND (attribute_not_exists(orderNumber) OR orderNumber=:number)',
        ExpressionAttributeValues={':id': order_id, ':number': order_number, ':wix': wix_order_id})
    orders.update_item(
        Key={'orderId': order_id},
        UpdateExpression='SET wixOrderId=:wix, sourceOrderId=:wix, updatedAt=:now',
        ConditionExpression='attribute_exists(orderId) AND orderNumber=:number AND (attribute_not_exists(wixOrderId) OR wixOrderId=:wix)',
        ExpressionAttributeValues={':wix': wix_order_id, ':number': order_number, ':now': int(time.time())})


def canonical_order_for_wix(orders, keys, wix_order_id):
    link = keys.get_item(Key={'orderId': wix_order_id}, ConsistentRead=True).get('Item') or {}
    internal_id = link.get('orderIdRef')
    if not internal_id:
        return None
    order = orders.get_item(Key={'orderId': internal_id}, ConsistentRead=True).get('Item') or {}
    if order.get('wixOrderId') != wix_order_id or order.get('orderNumber') != link.get('orderNumber'):
        raise ValueError('Wix/internal order association requires reconciliation')
    return order
