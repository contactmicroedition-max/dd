from django.contrib.auth.models import AbstractUser
from django.db import models


# ========== USER MODELS ==========
class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('agent', 'Agent'),
    ]
    
    THEME_CHOICES = [
        ('dark', 'Dark Modern'),
        ('light', 'Light Professional'),
        ('vibrant', 'Vibrant Neon'),
        ('sage', 'Sage Calm'),
        ('sand', 'Sandstone Soft'),
    ]

    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('ar', 'Arabic'),
        ('fr', 'French'),
    ]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='agent')
    is_approved = models.BooleanField(default=False, help_text="Admin must approve agents")
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=100, blank=True)
    google_id = models.CharField(max_length=200, blank=True, unique=True, null=True)
    email_verified = models.BooleanField(default=False)
    email_token = models.CharField(max_length=200, blank=True)
    remember_me = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='dark')
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='en')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_agent(self):
        return self.role == 'agent'

    @property
    def can_access(self):
        return self.is_admin or (self.is_agent and self.is_approved)


# ========== DRONE MODELS ==========
class Drone(models.Model):
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('charging', 'Charging'),
        ('maintenance', 'Maintenance'),
        ('patrolling', 'Patrolling'),
    ]

    name = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline')
    battery = models.IntegerField(default=100, help_text="Battery percentage 0-100")
    latitude = models.FloatField(default=36.8065)
    longitude = models.FloatField(default=10.1815)
    altitude = models.FloatField(default=0.0, help_text="Altitude in meters")
    speed = models.FloatField(default=0.0, help_text="Speed in km/h")
    camera_active = models.BooleanField(default=False)
    assigned_to = models.ForeignKey(CustomUser, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='assigned_drones')
    location_name = models.CharField(max_length=200, blank=True)
    stream_url = models.URLField(max_length=500, blank=True, help_text="MJPEG/HTTP video stream URL")
    image = models.ImageField(upload_to='drones/', null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.serial_number})"

    @property
    def status_color(self):
        colors = {
            'online': 'green', 'offline': 'gray', 'charging': 'yellow',
            'maintenance': 'orange', 'patrolling': 'blue',
        }
        return colors.get(self.status, 'gray')

    @property
    def battery_color(self):
        if self.battery >= 60:
            return 'green'
        elif self.battery >= 30:
            return 'yellow'
        return 'red'


# ========== ALERT MODELS ==========
class Alert(models.Model):
    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    TYPE_CHOICES = [
        ('intrusion', 'Intrusion Detected'),
        ('face', 'Face Recognized'),
        ('object', 'Object Detected'),
        ('motion', 'Motion Detected'),
        ('battery', 'Low Battery'),
        ('connection', 'Connection Lost'),
        ('geofence', 'Geofence Breach'),
        ('system', 'System Alert'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='medium')
    alert_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system')
    #drone = models.ForeignKey(Drone, null=True, blank=True,
    #                          on_delete=models.SET_NULL, related_name='alerts')
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(CustomUser, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='resolved_alerts')
    #thumbnail = models.ImageField(upload_to='alert_thumbs/', null=True, blank=True)
    #latitude = models.FloatField(null=True, blank=True)
    #longitude = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    #updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"

    @property
    def severity_color(self):
        return {'low': '#22c55e', 'medium': '#f59e0b',
                'high': '#f97316', 'critical': '#ef4444'}.get(self.severity, '#6b7280')

    @property
    def severity_class(self):
        return {'low': 'success', 'medium': 'warning',
                'high': 'orange', 'critical': 'danger'}.get(self.severity, 'info')


# ========== MONITORING MODELS ==========
class MonitoringLog(models.Model):
    drone = models.ForeignKey(Drone, on_delete=models.CASCADE, related_name='logs')
    event = models.CharField(max_length=200)
    details = models.TextField(blank=True)
    snapshot = models.ImageField(upload_to='snapshots/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.drone.name}: {self.event}"


class SecuritySystemLog(models.Model):
    EVENT_CHOICES = [
        ('alert_created', 'Alert Created'),
        ('alert_resolved', 'Alert Resolved'),
        ('detection_event', 'Detection Event'),
        ('drone_added', 'Drone Added'),
        ('drone_deployed', 'Drone Deployed'),
        ('drone_updated', 'Drone Updated'),
        ('drone_removed', 'Drone Removed'),
        ('recording_uploaded', 'Recording Uploaded'),
        ('recording_downloaded', 'Recording Downloaded'),
        ('recording_deleted', 'Recording Deleted'),
        ('user_login', 'User Logged In'),
        ('user_logout', 'User Logged Out'),
        ('user_approved', 'User Approved'),
        ('user_rejected', 'User Rejected'),
        ('system_event', 'System Event'),
    ]

    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]

    event_type = models.CharField(max_length=40, choices=EVENT_CHOICES, default='system_event')
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='info')
    source = models.CharField(max_length=50, default='system')
    message = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='security_logs')
    drone = models.ForeignKey(Drone, null=True, blank=True, on_delete=models.SET_NULL, related_name='security_logs')
    alert = models.ForeignKey(Alert, null=True, blank=True, on_delete=models.SET_NULL, related_name='security_logs')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'created_at']),
            models.Index(fields=['severity', 'created_at']),
            models.Index(fields=['source', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.event_type}: {self.message}"


class StreamRecording(models.Model):
    title = models.CharField(max_length=200)
    drone = models.ForeignKey(Drone, null=True, blank=True, on_delete=models.SET_NULL, related_name='recordings')
    recording_file = models.FileField(upload_to='stream_recordings/')
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='uploaded_recordings')
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.title


class LiveStreamControl(models.Model):
    STATE_CHOICES = [
        ('active', 'Active'),
        ('suspended', 'Temporarily Suspended'),
        ('shutdown', 'Shut Down'),
    ]

    singleton_key = models.CharField(max_length=30, unique=True, default='global', editable=False)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default='active')
    admin_note = models.CharField(max_length=255, blank=True)
    updated_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='live_stream_control_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Live stream state: {self.state}"


# ========== REPORTS MODELS ==========
class Report(models.Model):
    title = models.CharField(max_length=200)
    generated_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    period_start = models.DateField()
    period_end = models.DateField()
    total_alerts = models.IntegerField(default=0)
    critical_alerts = models.IntegerField(default=0)
    drones_active = models.IntegerField(default=0)
    faces_detected = models.IntegerField(default=0)
    objects_detected = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.period_start} – {self.period_end})"


# ========== DIRECT MESSAGES ==========
class AgentMessage(models.Model):
    sender = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='sent_agent_messages',
    )
    recipient = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='received_agent_messages',
    )
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
    )
    message = models.TextField(max_length=1000, blank=True)
    voice_message = models.FileField(upload_to='voice_messages/', null=True, blank=True)
    voice_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    attachment = models.FileField(upload_to='chat_attachments/', null=True, blank=True)
    is_broadcast = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    is_deleted_for_sender = models.BooleanField(default=False)
    is_deleted_for_recipient = models.BooleanField(default=False)
    deleted_for_everyone = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['sender', 'recipient', 'created_at']),
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['deleted_for_everyone', 'created_at']),
        ]

    def __str__(self):
        if self.message:
            preview = self.message[:40]
        elif self.attachment:
            preview = '[Attachment]'
        elif self.voice_message:
            preview = '[Voice message]'
        else:
            preview = '[Empty message]'
        return f"{self.sender.username} -> {self.recipient.username}: {preview}"


class AgentMessageReaction(models.Model):
    message = models.ForeignKey(
        AgentMessage,
        on_delete=models.CASCADE,
        related_name='reactions',
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='agent_message_reactions',
    )
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        indexes = [
            models.Index(fields=['message', 'emoji']),
        ]

    def __str__(self):
        return f"{self.user.username} reacted {self.emoji}"


class AIAssistantMessage(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='ai_assistant_messages',
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField(max_length=1200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['user', 'created_at'], name='core_aiassi_user_id_850ac3_idx'),
        ]

    def __str__(self):
        preview = (self.content or '')[:40]
        return f"{self.user.username} [{self.role}]: {preview}"
