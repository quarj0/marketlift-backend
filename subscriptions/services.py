from .models import SellerPlan, SellerSubscription


def get_effective_plan(seller):
    subscription = (
        SellerSubscription.objects.select_related("plan")
        .filter(seller=seller, status=SellerSubscription.Status.ACTIVE, plan__active=True)
        .first()
    )
    if subscription:
        return subscription.plan
    return SellerPlan.objects.filter(code="free", active=True).first()
