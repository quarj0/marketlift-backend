from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from commerce.delivery_security import encrypt_delivery_pin

from .commerce_models import Order, Shipment
from .delivery_models import DeliveryAssignment


@receiver(post_save, sender=Order, dispatch_uid="secure_local_delivery_pin_snapshot")
def secure_local_delivery_pin_snapshot(sender, instance: Order, **kwargs):
    """Encrypt and scrub a checkout PIN synchronously before its transaction commits."""
    if instance.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        return
    snapshot = dict(instance.listing_snapshot or {})
    pin = str(snapshot.pop("delivery_pin", "") or "").strip()
    if not pin:
        return
    try:
        shipment = instance.shipment
    except Shipment.DoesNotExist:
        # The checkout service creates the Shipment before it adds delivery_pin to
        # the order snapshot. Refuse an unexpected ordering rather than allowing
        # plaintext PIN material to be committed.
        raise ValidationError("Local delivery PIN cannot be persisted before shipment creation.")
    assignment, _ = DeliveryAssignment.objects.get_or_create(shipment=shipment)
    assignment.delivery_pin_ciphertext = encrypt_delivery_pin(pin)
    assignment.save(update_fields=("delivery_pin_ciphertext", "updated_at"))
    Order.objects.filter(pk=instance.pk).update(listing_snapshot=snapshot)
    instance.listing_snapshot = snapshot


@receiver(pre_save, sender=Order, dispatch_uid="guard_local_delivery_confirmation")
def guard_local_delivery_confirmation(sender, instance: Order, **kwargs):
    if instance.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        return
    if instance.status != Order.Status.DELIVERED or not instance.pk:
        return
    previous_status = (
        Order.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    )
    if previous_status == Order.Status.DELIVERED:
        return
    try:
        assignment = instance.shipment.delivery_assignment
    except (Shipment.DoesNotExist, DeliveryAssignment.DoesNotExist) as exc:
        raise ValidationError(
            "Local delivery must be confirmed by the assigned rider or an audited administrator override."
        ) from exc
    if assignment.confirmation_source not in {
        DeliveryAssignment.ConfirmationSource.RIDER_PIN,
        DeliveryAssignment.ConfirmationSource.ADMIN_OVERRIDE,
    }:
        raise ValidationError(
            "Local delivery must be confirmed by the assigned rider or an audited administrator override."
        )
