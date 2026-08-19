from django.contrib import admin
from .models import SupportTicket, SupportMessage

admin.site.register(SupportTicket)
admin.site.register(SupportMessage)
