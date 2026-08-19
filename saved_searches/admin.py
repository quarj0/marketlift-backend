from django.contrib import admin
from .models import SavedSearch, SavedSearchMatch

admin.site.register(SavedSearch)
admin.site.register(SavedSearchMatch)
