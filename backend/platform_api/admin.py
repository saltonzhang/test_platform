from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ApiInterface, AutomationModule, AutomationTask, AutomationTaskResult, Environment, Role, User


@admin.register(User)
class AibetUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('AIBET 信息', {'fields': ('name', 'role')}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('AIBET 信息', {'fields': ('name', 'email', 'role')}),)
    list_display = ('username', 'name', 'email', 'role', 'is_active')


admin.site.register(Role)
admin.site.register(Environment)
admin.site.register(AutomationModule)
admin.site.register(ApiInterface)
admin.site.register(AutomationTask)
admin.site.register(AutomationTaskResult)
