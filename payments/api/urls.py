from django.urls import path

from .views import MercadoPagoWebhookView, PaystackWebhookView

urlpatterns = [
    path(
        "mercado-pago/", MercadoPagoWebhookView.as_view(), name="mercado-pago-webhook"
    ),
    path("paystack/", PaystackWebhookView.as_view(), name="paystack-webhook"),
]
