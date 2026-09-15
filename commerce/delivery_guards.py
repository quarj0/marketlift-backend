from django.core.exceptions import ValidationError

from .models import Order
from .services import confirm_order_delivered


def buyer_confirm_non_local_delivery(*, order: Order, buyer, request=None) -> Order:
    """Keep buyer confirmation out of the local-rider delivery trust boundary.

    Local delivery is completed only by an assigned rider using the buyer's PIN,
    or by an explicitly audited administrator override. Shipping/pickup can keep
    using the existing buyer confirmation service.
    """
    if order.fulfillment_method == Order.FulfillmentMethod.LOCAL_DELIVERY:
        raise ValidationError(
            "Local delivery must be confirmed by the assigned rider using the buyer delivery PIN."
        )
    return confirm_order_delivered(order=order, buyer=buyer)
