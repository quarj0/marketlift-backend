from django.urls import path
from .views import MercadoPagoWebhookView

urlpatterns = [
    path("mercado-pago/", MercadoPagoWebhookView.as_view(), name="mercado-pago-webhook")
]
