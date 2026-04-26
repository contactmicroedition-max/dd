from django.urls import path
from django.urls import reverse_lazy
from django.contrib.auth import views as auth_views
from . import views
from .forms import CustomPasswordResetForm

app_name = 'core'

urlpatterns = [
    # ========== HOME & DASHBOARD ==========
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard_index, name='dashboard'),
    
    # ========== AUTH ==========
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('register/verify-email/', views.register_verify_email_code, name='register_verify_email_code'),
    path('logout/', views.logout_view, name='logout'),
    path('google/', views.google_login, name='google_login'),
    path('google/callback/', views.google_callback, name='google_callback'),
    # Backward-compatible aliases for OAuth redirect URIs configured with /users/ prefix.
    path('users/google/', views.google_login, name='google_login_users_alias'),
    path('users/google/callback/', views.google_callback, name='google_callback_users_alias'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            form_class=CustomPasswordResetForm,
            template_name='core/users/password_reset_form.html',
            email_template_name='core/users/password_reset_email.txt',
            subject_template_name='core/users/password_reset_subject.txt',
            success_url=reverse_lazy('core:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='core/users/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='core/users/password_reset_confirm.html',
            success_url=reverse_lazy('core:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='core/users/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    
    # ========== USERS/ADMIN ==========
    path('approve/<int:user_id>/', views.approve_agent, name='approve_agent'),
    path('reject/<int:user_id>/', views.reject_agent, name='reject_agent'),
    path('pending/', views.pending_agents, name='pending_agents'),
    path('agents/', views.agents_list, name='agents_list'),
    path('agents/<int:user_id>/elevate/', views.elevate_agent_to_admin, name='elevate_agent_to_admin'),
    path('agents/<int:user_id>/downgrade/', views.downgrade_admin_to_agent, name='downgrade_admin_to_agent'),
    path('agents/<int:user_id>/remove/', views.remove_agent, name='remove_agent'),
    path('agents/<int:user_id>/inspect/', views.inspect_agent, name='inspect_agent'),
    path('system/security-logs/', views.security_system_logs, name='security_system_logs'),
    path('system/security-logs/delete/', views.security_system_logs_delete, name='security_system_logs_delete'),
    path('system/recordings/', views.stream_recordings_admin, name='stream_recordings_admin'),
    path('system/recordings/<int:recording_id>/download/', views.stream_recording_download, name='stream_recording_download'),
    path('system/recordings/<int:recording_id>/delete/', views.stream_recording_delete, name='stream_recording_delete'),

    # ========== CHAT ==========
    path('chat/', views.chat_inbox, name='chat'),
    path('chat/<int:user_id>/', views.chat_inbox, name='chat_with_user'),
    path('chat/api/notifications/', views.chat_notifications_api, name='chat_notifications_api'),
    path('chat/api/<int:user_id>/conversation/delete/', views.chat_delete_conversation_api, name='chat_delete_conversation_api'),
    path('chat/api/<int:user_id>/messages/', views.chat_messages_api, name='chat_messages_api'),
    path('chat/api/<int:user_id>/send/', views.chat_send_api, name='chat_send_api'),
    path('chat/api/broadcast/send/', views.chat_broadcast_api, name='chat_broadcast_api'),
    path('chat/api/message/<int:message_id>/react/', views.chat_react_api, name='chat_react_api'),
    path('chat/api/message/<int:message_id>/delete/', views.chat_delete_message_api, name='chat_delete_message_api'),
    path('assistant/api/chat/', views.ai_assistant_chat_api, name='ai_assistant_chat_api'),
    
    # ========== SETTINGS/PROFILE ==========
    path('settings/', views.settings_index, name='settings'),
    path('settings/profile/', views.update_profile, name='update_profile'),
    path('settings/password/', views.change_password, name='change_password'),
    path('settings/password/forgot/', views.forgot_password_from_settings, name='forgot_password_from_settings'),
    
    # ========== DRONES ==========
    path('drones/', views.drone_list, name='drone_list'),
    path('drones/add/', views.drone_add, name='drone_add'),
    path('drones/<int:pk>/', views.drone_detail, name='drone_detail'),
    path('drones/<int:pk>/edit/', views.drone_edit, name='drone_edit'),
    path('drones/<int:pk>/delete/', views.drone_delete, name='drone_delete'),
    path('drones/<int:pk>/control/', views.drone_control, name='drone_control'),
    path('drones/<int:pk>/status/', views.drone_status_api, name='drone_status_api'),
    
    # ========== ALERTS ==========
    path('alerts/', views.alert_list, name='alert_list'),
    path('alerts/delete/all/', views.alert_delete_all, name='alert_delete_all'),
    path('alerts/<int:pk>/', views.alert_detail, name='alert_detail'),
    path('alerts/<int:pk>/resolve/', views.resolve_alert, name='resolve_alert'),
    path('alerts/<int:pk>/delete/', views.alert_delete, name='alert_delete'),
    path('alerts/api/live/', views.live_alerts_api, name='live_alerts_api'),
    path('alerts/api/simulate/', views.simulate_alert, name='simulate_alert'),
    
    # ========== MONITORING ==========
    path('monitoring/', views.live_stream, name='live_stream'),
    path('monitoring/<int:drone_id>/', views.live_stream, name='live_stream_drone'),
    path('monitoring/control/', views.live_stream_control, name='live_stream_control'),
    path('monitoring/logs/', views.monitoring_logs, name='monitoring_logs'),
    path('monitoring/api/feed/<int:drone_id>/', views.stream_feed_api, name='stream_feed_api'),
    
    # ========== REPORTS ==========
    path('reports/', views.reports_index, name='reports'),
    path('reports/api/chart/', views.chart_data_api, name='chart_data_api'),
]
