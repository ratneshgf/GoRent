from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *
admin.site.register(User, UserAdmin)
for m in (Vehicle, Booking, BookingEvent, Message, Review, AuditLog): admin.site.register(m)
