from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser,
    Drone,
    Alert,
    MonitoringLog,
    Report,
    AgentMessage,
    AgentMessageReaction,
    SecuritySystemLog,
    StreamRecording,
)


# ========== USER ADMIN ==========
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'get_full_name', 'role', 'is_approved', 'is_active', 'date_joined']
    list_filter = ['role', 'is_approved', 'is_active', 'email_verified']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering = ['-date_joined']
    actions = ['approve_agents', 'reject_agents']

    fieldsets = UserAdmin.fieldsets + (
        ('DroneSec Profile', {
            'fields': ('role', 'is_approved', 'avatar', 'phone', 'department',
                       'google_id', 'email_verified', 'last_seen')
        }),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('DroneSec Profile', {
            'fields': ('role', 'is_approved', 'email', 'first_name', 'last_name')
        }),
    )

    def approve_agents(self, request, queryset):
        queryset.filter(role='agent').update(is_approved=True)
        self.message_user(request, "Selected agents approved.")
    approve_agents.short_description = "✅ Approve selected agents"

    def reject_agents(self, request, queryset):
        queryset.filter(role='agent').update(is_approved=False, is_active=False)
        self.message_user(request, "Selected agents rejected.")
    reject_agents.short_description = "❌ Reject selected agents"


# ========== DRONE ADMIN ==========
@admin.register(Drone)
class DroneAdmin(admin.ModelAdmin):
    list_display = ['name', 'serial_number', 'status', 'battery', 'location_name', 'camera_active', 'updated_at']
    list_filter = ['status', 'camera_active']
    search_fields = ['name', 'serial_number', 'location_name']
    list_editable = ['status', 'camera_active']


# ========== ALERT ADMIN ==========
@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'severity', 'alert_type', 'drone', 'is_read', 'is_resolved', 'created_at']
    list_filter = ['severity', 'alert_type', 'is_read', 'is_resolved']
    search_fields = ['title', 'description']
    list_editable = ['is_read', 'is_resolved']
    date_hierarchy = 'created_at'


# ========== MONITORING LOG ADMIN ==========
@admin.register(MonitoringLog)
class MonitoringLogAdmin(admin.ModelAdmin):
    list_display = ['drone', 'event', 'created_at']
    list_filter = ['drone', 'created_at']
    search_fields = ['drone__name', 'event']
    date_hierarchy = 'created_at'


# ========== REPORT ADMIN ==========
@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['title', 'generated_by', 'period_start', 'period_end', 'created_at']
    list_filter = ['created_at', 'period_start']
    search_fields = ['title', 'generated_by__username']
    date_hierarchy = 'created_at'


# ========== CHAT ADMIN ==========
@admin.register(AgentMessage)
class AgentMessageAdmin(admin.ModelAdmin):
    list_display = ['sender', 'recipient', 'short_message', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']
    search_fields = ['sender__username', 'recipient__username', 'message']
    date_hierarchy = 'created_at'

    def short_message(self, obj):
        if obj.message:
            return obj.message[:80]
        if obj.attachment:
            return '[Attachment]'
        if obj.voice_message:
            return '[Voice message]'
        return ''

    short_message.short_description = 'Message'


@admin.register(AgentMessageReaction)
class AgentMessageReactionAdmin(admin.ModelAdmin):
    list_display = ['message', 'user', 'emoji', 'created_at']
    list_filter = ['emoji', 'created_at']
    search_fields = ['user__username', 'message__message']


@admin.register(SecuritySystemLog)
class SecuritySystemLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'event_type', 'severity', 'source', 'short_message', 'user', 'drone', 'alert']
    list_filter = ['event_type', 'severity', 'source', 'created_at']
    search_fields = ['message', 'source', 'user__username', 'drone__name', 'alert__title']
    date_hierarchy = 'created_at'

    def short_message(self, obj):
        return (obj.message or '')[:90]

    short_message.short_description = 'Message'


@admin.register(StreamRecording)
class StreamRecordingAdmin(admin.ModelAdmin):
    list_display = ['title', 'drone', 'uploaded_by', 'duration_seconds', 'file_size_bytes', 'created_at']
    list_filter = ['drone', 'created_at']
    search_fields = ['title', 'description', 'drone__name', 'uploaded_by__username']
    date_hierarchy = 'created_at'
