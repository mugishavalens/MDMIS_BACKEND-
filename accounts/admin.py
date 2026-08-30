from django.contrib import admin

from .models import Organisation, User


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'country_code', 'license_tier', 'is_active', 'created_at')
    search_fields = ('name', 'slug')
    list_filter = ('country_code', 'license_tier', 'is_active')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'role', 'organisation', 'is_active', 'is_staff')
    list_filter = ('role', 'is_active', 'organisation')
    search_fields = ('email', 'full_name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('email',)}),
        ('Profile', {'fields': ('full_name', 'role', 'organisation')}),
        ('Status', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_email_verified')}),
        ('Dates', {'fields': ('created_at', 'updated_at')}),
    )
    ordering = ('-created_at',)
