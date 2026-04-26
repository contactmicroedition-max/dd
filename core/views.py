import uuid
import json
import os
import mimetypes
import re
import requests
import random
import time
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.hashers import make_password
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.http import JsonResponse, FileResponse
from django.db.models import Q, Count
from django.db.utils import OperationalError, ProgrammingError
from django.views.decorators.http import require_POST, require_http_methods
from datetime import timedelta, datetime, time as dt_time

from .models import (
    CustomUser,
    Drone,
    Alert,
    MonitoringLog,
    Report,
    AgentMessage,
    AgentMessageReaction,
    AIAssistantMessage,
    SecuritySystemLog,
    StreamRecording,
    LiveStreamControl,
)
from .forms import (
    LoginForm,
    RegisterForm,
    ProfileUpdateForm,
    CustomPasswordChangeForm,
    CustomSetPasswordForm,
    CustomPasswordResetForm,
    StreamRecordingUploadForm,
)


CHAT_VOICE_MAX_BYTES = 10 * 1024 * 1024
CHAT_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
CHAT_VOICE_ALLOWED_TYPES = {
    'audio/webm',
    'audio/ogg',
    'audio/wav',
    'audio/x-wav',
    'audio/mpeg',
    'audio/mp4',
    'audio/aac',
}
CHAT_VOICE_ALLOWED_EXTENSIONS = {
    '.webm',
    '.ogg',
    '.wav',
    '.mp3',
    '.m4a',
    '.aac',
}
CHAT_IMAGE_EXTENSIONS = {
    '.jpg',
    '.jpeg',
    '.png',
    '.gif',
    '.webp',
    '.bmp',
}

REGISTER_PENDING_DATA_KEY = 'register_pending_data'
REGISTER_VERIFY_EMAIL_KEY = 'register_verify_email'
REGISTER_VERIFY_CODE_KEY = 'register_verify_code'
REGISTER_VERIFY_EXPIRY_KEY = 'register_verify_expiry'
REGISTER_VERIFY_ATTEMPTS_KEY = 'register_verify_attempts'


def get_lang(request, default='en'):
    if request.user.is_authenticated and getattr(request.user, 'language', None):
        return request.user.language
    return request.session.get('preferred_language', default)


def tr(lang, en, ar, fr):
    return {
        'ar': ar,
        'fr': fr,
        'en': en,
    }.get(lang, en)


def _is_reserved_main_admin(user):
    username = (getattr(user, 'username', '') or '').strip().lower()
    return username == 'admin'


def _user_avatar_url(user):
    try:
        if getattr(user, 'avatar', None) and user.avatar.name:
            return user.avatar.url
    except Exception:
        return ''
    return ''


def _touch_last_seen(user, min_interval_seconds=45):
    now = timezone.now()
    if not user.last_seen or (now - user.last_seen).total_seconds() >= min_interval_seconds:
        user.last_seen = now
        user.save(update_fields=['last_seen'])


def _is_message_visible_to_user(message, user):
    if message.deleted_for_everyone:
        return False
    if message.sender_id == user.id:
        return not message.is_deleted_for_sender
    if message.recipient_id == user.id:
        return not message.is_deleted_for_recipient
    return False


def _visible_messages_for_user(user):
    return AgentMessage.objects.filter(
        deleted_for_everyone=False,
    ).filter(
        Q(sender=user, is_deleted_for_sender=False)
        | Q(recipient=user, is_deleted_for_recipient=False)
    )


def _conversation_messages_for_user(user, peer):
    return _visible_messages_for_user(user).filter(
        Q(sender=user, recipient=peer) | Q(sender=peer, recipient=user)
    )


def _unread_messages_for_user(user):
    return AgentMessage.objects.filter(
        recipient=user,
        is_read=False,
        deleted_for_everyone=False,
        is_deleted_for_recipient=False,
    )


def _voice_message_url(message):
    try:
        if getattr(message, 'voice_message', None) and message.voice_message.name:
            return message.voice_message.url
    except Exception:
        return ''
    return ''


def _attachment_url(message):
    try:
        if getattr(message, 'attachment', None) and message.attachment.name:
            return message.attachment.url
    except Exception:
        return ''
    return ''


def _attachment_name(message):
    attachment = getattr(message, 'attachment', None)
    if not attachment or not attachment.name:
        return ''
    return os.path.basename(attachment.name)


def _attachment_is_image(message):
    attachment = getattr(message, 'attachment', None)
    if not attachment or not attachment.name:
        return False

    extension = os.path.splitext(attachment.name)[1].lower()
    if extension in CHAT_IMAGE_EXTENSIONS:
        return True

    guessed_type, _ = mimetypes.guess_type(attachment.name)
    return bool(guessed_type and guessed_type.startswith('image/'))


def _message_preview_text(message, lang='en'):
    if message.message:
        return message.message
    if getattr(message, 'attachment', None):
        if _attachment_is_image(message):
            return tr(lang, 'Image attachment', 'صورة مرفقة', 'Image jointe')
        return tr(lang, 'File attachment', 'ملف مرفق', 'Fichier joint')
    if getattr(message, 'voice_message', None):
        return tr(lang, 'Voice message', 'رسالة صوتية', 'Message vocal')
    return ''


def _is_valid_voice_upload(uploaded_file):
    content_type = (getattr(uploaded_file, 'content_type', '') or '').lower()
    extension = os.path.splitext(uploaded_file.name or '')[1].lower()
    if content_type in CHAT_VOICE_ALLOWED_TYPES:
        return True
    if extension in CHAT_VOICE_ALLOWED_EXTENSIONS:
        return True
    return False


def _serialize_chat_message(message, current_user):
    is_mine = message.sender_id == current_user.id
    lang = getattr(current_user, 'language', 'en')
    my_reaction = message.reactions.filter(user=current_user).values_list('emoji', flat=True).first()
    reactions = [
        {
            'emoji': row['emoji'],
            'count': row['total'],
            'mine': bool(my_reaction and my_reaction == row['emoji']),
        }
        for row in message.reactions.values('emoji').annotate(total=Count('id')).order_by('-total', 'emoji')
    ]

    reply_payload = None
    if message.reply_to and _is_message_visible_to_user(message.reply_to, current_user):
        reply_payload = {
            'id': message.reply_to_id,
            'sender_name': message.reply_to.sender.get_full_name() or message.reply_to.sender.username,
            'message': _message_preview_text(message.reply_to, lang),
            'has_voice': bool(message.reply_to.voice_message),
            'has_attachment': bool(message.reply_to.attachment),
            'attachment_is_image': _attachment_is_image(message.reply_to),
        }

    return {
        'id': message.id,
        'message': message.message,
        'message_preview': _message_preview_text(message, lang),
        'is_broadcast': bool(message.is_broadcast),
        'has_voice': bool(message.voice_message),
        'voice_url': _voice_message_url(message),
        'voice_duration_seconds': message.voice_duration_seconds,
        'has_attachment': bool(message.attachment),
        'attachment_url': _attachment_url(message),
        'attachment_name': _attachment_name(message),
        'attachment_is_image': _attachment_is_image(message),
        'is_mine': is_mine,
        'sender_id': message.sender_id,
        'sender_name': message.sender.get_full_name() or message.sender.username,
        'created_at': timezone.localtime(message.created_at).strftime('%H:%M'),
        'created_at_full': timezone.localtime(message.created_at).strftime('%Y-%m-%d %H:%M'),
        'reply_to': reply_payload,
        'reactions': reactions,
        'is_seen': bool(message.is_read) if is_mine else None,
        'can_delete_self': message.sender_id == current_user.id,
        'can_delete_for_both': message.sender_id == current_user.id,
    }


def _assistant_page_hint(query_text, lang):
    q = (query_text or '').lower()
    pages = [
        (['dashboard', 'home', 'overview'], '/dashboard/', tr(lang, 'dashboard overview', 'نظرة عامة على اللوحة', "vue d'ensemble du tableau")),
        (['alert', 'alerts'], '/alerts/', tr(lang, 'alerts center', 'مركز التنبيهات', 'centre des alertes')),
        (['drone', 'drones'], '/drones/', tr(lang, 'drones list', 'قائمة الطائرات', 'liste des drones')),
        (['monitor', 'monitoring', 'live stream', 'stream'], '/monitoring/', tr(lang, 'live monitoring', 'المراقبة المباشرة', 'surveillance en direct')),
        (['report', 'reports', 'analytics', 'chart'], '/reports/', tr(lang, 'reports and analytics', 'التقارير والتحليلات', 'rapports et analyses')),
        (['chat', 'message', 'messages', 'inbox'], '/chat/', tr(lang, 'team chat', 'محادثة الفريق', "messagerie d'equipe")),
        (['setting', 'settings', 'profile', 'password'], '/settings/', tr(lang, 'settings page', 'صفحة الاعدادات', 'page des parametres')),
    ]

    for keywords, path, label in pages:
        if any(word in q for word in keywords):
            return tr(
                lang,
                f"Open {label} at {path}",
                f"يمكنك فتح {label} عبر {path}",
                f"Ouvrez {label} ici : {path}",
            )
    return ''


def _assistant_alert_action_text(alert, lang):
    if alert.is_resolved:
        return tr(
            lang,
            'This alert is already resolved. You can review details and related logs.',
            'هذا التنبيه محلول بالفعل. يمكنك مراجعة التفاصيل والسجلات المرتبطة.',
            'Cette alerte est deja resolue. Vous pouvez consulter les details et les journaux associes.',
        )

    if alert.severity == 'critical':
        return tr(
            lang,
            'Recommended action: acknowledge immediately, open live monitoring, assign nearest online drone, then resolve only after verification.',
            'الاجراء المقترح: قم بالتأكيد فورا، افتح المراقبة المباشرة، عيّن اقرب طائرة متصلة، ثم قم بالحل بعد التحقق.',
            'Action recommandee : accusez reception immediatement, ouvrez la surveillance en direct, assignez le drone en ligne le plus proche, puis resolvez apres verification.',
        )
    if alert.severity == 'high':
        return tr(
            lang,
            'Recommended action: inspect alert details, verify drone status, and escalate if repeated in the same zone.',
            'الاجراء المقترح: افحص تفاصيل التنبيه، تحقق من حالة الطائرة، وصعّد الحالة اذا تكرر في نفس المنطقة.',
            "Action recommandee : verifiez les details de l'alerte, verifiez le statut du drone et escaladez si elle se repete dans la meme zone.",
        )
    return tr(
        lang,
        'Recommended action: monitor the situation and keep the alert open until confirmed stable.',
        'الاجراء المقترح: راقب الحالة وابقِ التنبيه مفتوحا حتى يتأكد الاستقرار.',
        'Action recommandee : surveillez la situation et gardez l alerte ouverte jusqu a confirmation de stabilite.',
    )


def _assistant_alert_summary(lang):
    unresolved = Alert.objects.filter(is_resolved=False)
    critical = unresolved.filter(severity='critical').count()
    high = unresolved.filter(severity='high').count()
    total = unresolved.count()

    latest = unresolved.select_related('drone').order_by('-created_at').first()
    if latest:
        latest_line = tr(
            lang,
            f"Latest unresolved alert: #{latest.id} {latest.title}",
            f"احدث تنبيه غير محلول: #{latest.id} {latest.title}",
            f"Derniere alerte non resolue : #{latest.id} {latest.title}",
        )
    else:
        latest_line = tr(lang, 'There are no unresolved alerts right now.', 'لا توجد تنبيهات غير محلولة حاليا.', "Il n y a aucune alerte non resolue pour le moment.")

    return tr(
        lang,
        f"Unresolved alerts: {total} (critical: {critical}, high: {high}). {latest_line}",
        f"التنبيهات غير المحلولة: {total} (حرجة: {critical}، عالية: {high}). {latest_line}",
        f"Alertes non resolues : {total} (critiques : {critical}, elevees : {high}). {latest_line}",
    )


def _assistant_operational_context(lang):
    agent_presence = _assistant_agent_presence_stats()
    total_drones = Drone.objects.count()
    online_count = Drone.objects.filter(status__in=['online', 'patrolling']).count()
    charging_count = Drone.objects.filter(status='charging').count()
    offline_count = Drone.objects.filter(status='offline').count()
    unresolved_alerts = Alert.objects.filter(is_resolved=False).count()

    return tr(
        lang,
        (
            'Live DroneSec operational context (authoritative DB snapshot): '
            f'total_drones={total_drones}, '
            f'online_or_patrolling={online_count}, '
            f'charging={charging_count}, '
            f'offline={offline_count}, '
            f'unresolved_alerts={unresolved_alerts}, '
            f'agents_online_now={agent_presence["online_now"]}, '
            f'agents_idle_lt_1h={agent_presence["idle"]}, '
            f'agents_offline={agent_presence["offline"]}, '
            f'agents_never_logged={agent_presence["never_logged"]}. '
            'When user asks for counts or status, use these values exactly.'
        ),
        (
            'سياق DroneSec المباشر (لقطة موثوقة من قاعدة البيانات): '
            f'اجمالي_الطائرات={total_drones}, '
            f'متصلة_او_بدورية={online_count}, '
            f'قيد_الشحن={charging_count}, '
            f'غير_متصلة={offline_count}, '
            f'تنبيهات_غير_محلولة={unresolved_alerts}, '
            f'الوكلاء_المتصلون_الآن={agent_presence["online_now"]}, '
            f'الوكلاء_خامل_اقل_من_ساعة={agent_presence["idle"]}, '
            f'الوكلاء_غير_متصلين={agent_presence["offline"]}, '
            f'الوكلاء_لم_يسجلوا_دخول={agent_presence["never_logged"]}. '
            'عند سؤال المستخدم عن الاعداد او الحالة، استخدم هذه القيم كما هي.'
        ),
        (
            'Contexte operationnel DroneSec en direct (snapshot BD de reference) : '
            f'total_drones={total_drones}, '
            f'en_ligne_ou_patrouille={online_count}, '
            f'en_charge={charging_count}, '
            f'hors_ligne={offline_count}, '
            f'alertes_non_resolues={unresolved_alerts}, '
            f'agents_en_ligne_maintenant={agent_presence["online_now"]}, '
            f'agents_inactifs_moins_1h={agent_presence["idle"]}, '
            f'agents_hors_ligne={agent_presence["offline"]}, '
            f'agents_jamais_connectes={agent_presence["never_logged"]}. '
            'Si l utilisateur demande des nombres/statuts, utilisez exactement ces valeurs.'
        ),
    )


def _assistant_detailed_alert_context(lang, limit=8):
    alerts = list(
        Alert.objects.select_related('drone')
        .filter(is_resolved=False)
        .order_by('-created_at')[:limit]
    )
    if not alerts:
        return tr(
            lang,
            'Detailed unresolved alert context: none.',
            'سياق التنبيهات غير المحلولة بالتفصيل: لا يوجد.',
            'Contexte detaille des alertes non resolues : aucun.',
        )

    lines = []
    for alert in alerts:
        drone_name = alert.drone.name if alert.drone else tr(lang, 'System', 'النظام', 'Systeme')
        location = (alert.drone.location_name if alert.drone and alert.drone.location_name else '')
        if not location and alert.latitude is not None and alert.longitude is not None:
            location = f'{alert.latitude:.4f},{alert.longitude:.4f}'
        if not location:
            location = tr(lang, 'Unknown', 'غير محدد', 'Inconnue')

        description = (alert.description or '').strip().replace('\n', ' ')
        if len(description) > 180:
            description = description[:180].rstrip() + '...'

        lines.append(
            f'#{alert.id} | severity={alert.severity} | type={alert.alert_type} | '
            f'title={alert.title} | drone={drone_name} | location={location} | '
            f'created={timezone.localtime(alert.created_at).strftime("%Y-%m-%d %H:%M")} | '
            f'description={description}'
        )

    header = tr(
        lang,
        'Detailed unresolved alert context:',
        'سياق التنبيهات غير المحلولة بالتفصيل:',
        'Contexte detaille des alertes non resolues :',
    )
    return header + '\n' + '\n'.join(lines)


def _assistant_latest_critical_alert_detail(lang):
    alert = (
        Alert.objects.select_related('drone')
        .filter(is_resolved=False, severity='critical')
        .order_by('-created_at')
        .first()
    )
    if not alert:
        return tr(
            lang,
            'There is no unresolved critical alert right now.',
            'لا يوجد حاليا تنبيه حرج غير محلول.',
            'Il n y a pas d alerte critique non resolue actuellement.',
        )

    drone_name = alert.drone.name if alert.drone else tr(lang, 'System', 'النظام', 'Systeme')
    location = (alert.drone.location_name if alert.drone and alert.drone.location_name else '')
    if not location and alert.latitude is not None and alert.longitude is not None:
        location = f'{alert.latitude:.4f},{alert.longitude:.4f}'
    if not location:
        location = tr(lang, 'Unknown', 'غير محدد', 'Inconnue')

    return tr(
        lang,
        (
            f'Latest critical unresolved alert is #{alert.id}: {alert.title}. '
            f'Type: {alert.alert_type}. Drone: {drone_name}. Location: {location}. '
            f'Time: {timezone.localtime(alert.created_at).strftime("%Y-%m-%d %H:%M")}. '
            f'Description: {alert.description}'
        ),
        (
            f'احدث تنبيه حرج غير محلول هو #{alert.id}: {alert.title}. '
            f'النوع: {alert.alert_type}. الطائرة: {drone_name}. الموقع: {location}. '
            f'الوقت: {timezone.localtime(alert.created_at).strftime("%Y-%m-%d %H:%M")}. '
            f'الوصف: {alert.description}'
        ),
        (
            f'Derniere alerte critique non resolue : #{alert.id} {alert.title}. '
            f'Type : {alert.alert_type}. Drone : {drone_name}. Lieu : {location}. '
            f'Heure : {timezone.localtime(alert.created_at).strftime("%Y-%m-%d %H:%M")}. '
            f'Description : {alert.description}'
        ),
    )


def _assistant_compact_text(value, max_len=120):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 3)].rstrip() + '...'


def _assistant_presence_bucket(last_seen, now=None):
    if not last_seen:
        return 'never'
    now = now or timezone.now()
    delta = now - last_seen
    if delta < timedelta(minutes=5):
        return 'online_now'
    if delta < timedelta(hours=1):
        return 'idle'
    return 'offline'


def _assistant_agent_presence_stats():
    now = timezone.now()
    approved_active_agents = CustomUser.objects.filter(role='agent', is_approved=True, is_active=True)
    five_minutes_ago = now - timedelta(minutes=5)
    one_hour_ago = now - timedelta(hours=1)

    total = approved_active_agents.count()
    online_now = approved_active_agents.filter(last_seen__gte=five_minutes_ago).count()
    idle = approved_active_agents.filter(last_seen__lt=five_minutes_ago, last_seen__gte=one_hour_ago).count()
    offline = approved_active_agents.filter(last_seen__lt=one_hour_ago, last_seen__isnull=False).count()
    never_logged = approved_active_agents.filter(last_seen__isnull=True).count()

    return {
        'total': total,
        'online_now': online_now,
        'idle': idle,
        'offline': offline,
        'never_logged': never_logged,
    }


def _assistant_agent_presence_reply(lang):
    stats = _assistant_agent_presence_stats()
    return tr(
        lang,
        (
            f"Approved active agents: {stats['total']}. "
            f"Online now: {stats['online_now']} (last seen within 5 minutes). "
            f"Idle (5-60 minutes): {stats['idle']}. "
            f"Offline (>60 minutes): {stats['offline']}. "
            f"Never logged in: {stats['never_logged']}."
        ),
        (
            f"الوكلاء المعتمدون والنشطون: {stats['total']}. "
            f"المتصلون الآن: {stats['online_now']} (آخر ظهور خلال 5 دقائق). "
            f"خاملون (من 5 إلى 60 دقيقة): {stats['idle']}. "
            f"غير متصلين (أكثر من 60 دقيقة): {stats['offline']}. "
            f"لم يسجلوا الدخول من قبل: {stats['never_logged']}."
        ),
        (
            f"Agents approuves et actifs : {stats['total']}. "
            f"En ligne maintenant : {stats['online_now']} (derniere activite dans les 5 minutes). "
            f"Inactifs (5-60 minutes) : {stats['idle']}. "
            f"Hors ligne (>60 minutes) : {stats['offline']}. "
            f"Jamais connectes : {stats['never_logged']}."
        ),
    )


def _assistant_db_overview_context(lang):
    limit = max(2, min(12, int(getattr(settings, 'AI_ASSISTANT_DB_CONTEXT_LIMIT', 5) or 5)))
    now_for_presence = timezone.now()
    agent_presence = _assistant_agent_presence_stats()

    total_users = CustomUser.objects.count()
    total_admins = CustomUser.objects.filter(role='admin').count()
    total_agents = CustomUser.objects.filter(role='agent').count()
    approved_agents = CustomUser.objects.filter(role='agent', is_approved=True).count()
    pending_agents = CustomUser.objects.filter(role='agent', is_approved=False).count()

    total_drones = Drone.objects.count()
    drone_status_counts = {
        row['status']: row['total']
        for row in Drone.objects.values('status').annotate(total=Count('id'))
    }

    total_alerts = Alert.objects.count()
    unresolved_alerts = Alert.objects.filter(is_resolved=False).count()
    resolved_alerts = total_alerts - unresolved_alerts
    alert_severity_counts = {
        row['severity']: row['total']
        for row in Alert.objects.filter(is_resolved=False).values('severity').annotate(total=Count('id'))
    }

    total_reports = Report.objects.count()
    total_messages = AgentMessage.objects.count()
    unread_messages = AgentMessage.objects.filter(is_read=False, deleted_for_everyone=False).count()

    users = list(
        CustomUser.objects.order_by('-id').values(
            'id', 'username', 'role', 'is_approved', 'is_active', 'last_login', 'last_seen', 'created_at'
        )[:limit]
    )
    drones = list(
        Drone.objects.select_related('assigned_to').order_by('-id')[:limit]
    )
    alerts = list(
        Alert.objects.select_related('drone').order_by('-created_at')[:limit]
    )
    reports = list(
        Report.objects.select_related('generated_by').order_by('-created_at')[:limit]
    )
    messages_rows = list(
        AgentMessage.objects.select_related('sender', 'recipient').order_by('-created_at')[:limit]
    )

    user_lines = []
    for u in users:
        login_at = timezone.localtime(u['last_login']).strftime('%Y-%m-%d %H:%M') if u['last_login'] else 'never'
        seen_at = timezone.localtime(u['last_seen']).strftime('%Y-%m-%d %H:%M') if u['last_seen'] else 'never'
        presence = _assistant_presence_bucket(u['last_seen'], now=now_for_presence)
        user_lines.append(
            f"#{u['id']} {u['username']} role={u['role']} approved={int(bool(u['is_approved']))} "
            f"active={int(bool(u['is_active']))} presence={presence} last_seen={seen_at} last_login={login_at}"
        )

    drone_lines = []
    for d in drones:
        assignee = d.assigned_to.username if d.assigned_to else '-'
        loc = _assistant_compact_text(d.location_name or '', 40) or '-'
        drone_lines.append(
            f"#{d.id} {d.name} status={d.status} battery={d.battery}% assigned_to={assignee} location={loc}"
        )

    alert_lines = []
    for a in alerts:
        drone_name = a.drone.name if a.drone else 'System'
        alert_lines.append(
            f"#{a.id} {a.severity}/{a.alert_type} resolved={int(bool(a.is_resolved))} read={int(bool(a.is_read))} "
            f"drone={drone_name} title={_assistant_compact_text(a.title, 70)} "
            f"at={timezone.localtime(a.created_at).strftime('%Y-%m-%d %H:%M')}"
        )

    report_lines = []
    for r in reports:
        owner = r.generated_by.username if r.generated_by else '-'
        report_lines.append(
            f"#{r.id} {r.title} by={owner} range={r.period_start}..{r.period_end} "
            f"alerts={r.total_alerts} critical={r.critical_alerts}"
        )

    message_lines = []
    for m in messages_rows:
        preview = _assistant_compact_text(m.message or '[attachment/voice]', 70)
        message_lines.append(
            f"#{m.id} {m.sender.username}->{m.recipient.username} read={int(bool(m.is_read))} "
            f"broadcast={int(bool(m.is_broadcast))} text={preview} "
            f"at={timezone.localtime(m.created_at).strftime('%Y-%m-%d %H:%M')}"
        )

    status_part = ', '.join([
        f"online={drone_status_counts.get('online', 0)}",
        f"patrolling={drone_status_counts.get('patrolling', 0)}",
        f"charging={drone_status_counts.get('charging', 0)}",
        f"offline={drone_status_counts.get('offline', 0)}",
        f"maintenance={drone_status_counts.get('maintenance', 0)}",
    ])
    severity_part = ', '.join([
        f"critical={alert_severity_counts.get('critical', 0)}",
        f"high={alert_severity_counts.get('high', 0)}",
        f"medium={alert_severity_counts.get('medium', 0)}",
        f"low={alert_severity_counts.get('low', 0)}",
    ])

    now_label = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    agent_presence_part = (
        f"agent_presence(approved_active): online_now={agent_presence['online_now']}, "
        f"idle_lt_1h={agent_presence['idle']}, offline={agent_presence['offline']}, "
        f"never_logged={agent_presence['never_logged']}"
    )
    return tr(
        lang,
        (
            f"Live DB snapshot ({now_label}) - authoritative and refreshed on every request.\n"
            f"Totals: users={total_users} (admins={total_admins}, agents={total_agents}, approved_agents={approved_agents}, pending_agents={pending_agents}); "
            f"{agent_presence_part}; "
            f"drones={total_drones} ({status_part}); "
            f"alerts={total_alerts} (unresolved={unresolved_alerts}, resolved={resolved_alerts}, unresolved_by_severity: {severity_part}); "
            f"reports={total_reports}; messages={total_messages} (unread={unread_messages}).\n"
            f"Latest users (max {limit}):\n" + ('\n'.join(user_lines) if user_lines else 'none') + "\n"
            f"Latest drones (max {limit}):\n" + ('\n'.join(drone_lines) if drone_lines else 'none') + "\n"
            f"Latest alerts (max {limit}):\n" + ('\n'.join(alert_lines) if alert_lines else 'none') + "\n"
            f"Latest reports (max {limit}):\n" + ('\n'.join(report_lines) if report_lines else 'none') + "\n"
            f"Latest messages (max {limit}):\n" + ('\n'.join(message_lines) if message_lines else 'none')
        ),
        (
            f"لقطة مباشرة من قاعدة البيانات ({now_label}) - مرجعية ويتم تحديثها مع كل طلب.\n"
            f"الاجماليات: users={total_users} (admins={total_admins}, agents={total_agents}, approved_agents={approved_agents}, pending_agents={pending_agents}); "
            f"{agent_presence_part}; "
            f"drones={total_drones} ({status_part}); "
            f"alerts={total_alerts} (unresolved={unresolved_alerts}, resolved={resolved_alerts}, unresolved_by_severity: {severity_part}); "
            f"reports={total_reports}; messages={total_messages} (unread={unread_messages}).\n"
            f"احدث المستخدمين (حد اقصى {limit}):\n" + ('\n'.join(user_lines) if user_lines else 'none') + "\n"
            f"احدث الطائرات (حد اقصى {limit}):\n" + ('\n'.join(drone_lines) if drone_lines else 'none') + "\n"
            f"احدث التنبيهات (حد اقصى {limit}):\n" + ('\n'.join(alert_lines) if alert_lines else 'none') + "\n"
            f"احدث التقارير (حد اقصى {limit}):\n" + ('\n'.join(report_lines) if report_lines else 'none') + "\n"
            f"احدث الرسائل (حد اقصى {limit}):\n" + ('\n'.join(message_lines) if message_lines else 'none')
        ),
        (
            f"Snapshot BD en direct ({now_label}) - reference et rafraichi a chaque requete.\n"
            f"Totaux : users={total_users} (admins={total_admins}, agents={total_agents}, approved_agents={approved_agents}, pending_agents={pending_agents}); "
            f"{agent_presence_part}; "
            f"drones={total_drones} ({status_part}); "
            f"alerts={total_alerts} (unresolved={unresolved_alerts}, resolved={resolved_alerts}, unresolved_by_severity: {severity_part}); "
            f"reports={total_reports}; messages={total_messages} (unread={unread_messages}).\n"
            f"Derniers utilisateurs (max {limit}) :\n" + ('\n'.join(user_lines) if user_lines else 'none') + "\n"
            f"Derniers drones (max {limit}) :\n" + ('\n'.join(drone_lines) if drone_lines else 'none') + "\n"
            f"Dernieres alertes (max {limit}) :\n" + ('\n'.join(alert_lines) if alert_lines else 'none') + "\n"
            f"Derniers rapports (max {limit}) :\n" + ('\n'.join(report_lines) if report_lines else 'none') + "\n"
            f"Derniers messages (max {limit}) :\n" + ('\n'.join(message_lines) if message_lines else 'none')
        ),
    )


def _assistant_direct_fact_reply(query_text, lang):
    q = (query_text or '').strip().lower()
    if not q:
        return ''

    db_scope_phrases = [
        'database',
        'db',
        'what do you know',
        'what data do you have',
        'what does the website have',
        'website data',
        'قاعدة البيانات',
        'ماذا تعرف',
        'qu est ce que tu sais',
        'base de donnees',
    ]
    if any(phrase in q for phrase in db_scope_phrases):
        return _assistant_db_overview_context(lang)

    looks_for_agents = any(token in q for token in [
        'agent', 'agents', 'وكيل', 'وكلاء', 'الوكيل', 'الوكلاء',
    ])
    looks_for_presence = any(token in q for token in [
        'online', 'online now', 'currently online', 'active now', 'en ligne',
        'متصل', 'متصلين', 'الآن', 'نشط', 'actif', 'connecte',
    ])
    if looks_for_agents and looks_for_presence:
        return _assistant_agent_presence_reply(lang)

    drone_count_phrases = [
        'how many drones',
        'number of drones',
        'total drones',
        'combien de drones',
        'كم طائرة',
        'عدد الطائرات',
    ]
    if any(phrase in q for phrase in drone_count_phrases):
        total_drones = Drone.objects.count()
        online_count = Drone.objects.filter(status__in=['online', 'patrolling']).count()
        charging_count = Drone.objects.filter(status='charging').count()
        offline_count = Drone.objects.filter(status='offline').count()
        return tr(
            lang,
            f'You currently have {total_drones} drones in total: online/patrolling {online_count}, charging {charging_count}, offline {offline_count}.',
            f'لديكم حاليا {total_drones} طائرة بالمجموع: متصلة/في دورية {online_count}، قيد الشحن {charging_count}، غير متصلة {offline_count}.',
            f'Vous avez actuellement {total_drones} drones au total : en ligne/patrouille {online_count}, en charge {charging_count}, hors ligne {offline_count}.',
        )

    critical_detail_phrases = [
        'critical alert',
        'critical incident',
        'which alert is critical',
        'details of critical',
        'تنبيه حرج',
        'alerte critique',
    ]
    if any(phrase in q for phrase in critical_detail_phrases):
        return _assistant_latest_critical_alert_detail(lang)

    return ''


def _assistant_incident_action_guide(lang):
    return tr(
        lang,
        (
            'Good question. If you get an incident alert, use this sequence: '
            '1) confirm severity and location, '
            '2) open live monitoring and verify the feed for 30-60 seconds, '
            '3) dispatch the nearest available drone and assign ownership, '
            '4) document what you observed and notify the team if risk is high, '
            '5) resolve only after verification is complete. '
            'If you share the alert id, I can tell you the exact next action for that specific case.'
        ),
        (
            'سؤال ممتاز. عند وصول تنبيه حادثة اتبع هذا التسلسل: '
            '1) تاكد من الشدة والموقع، '
            '2) افتح المراقبة المباشرة وتحقق من البث لمدة 30-60 ثانية، '
            '3) عيّن اقرب طائرة متاحة وحدد المسؤول، '
            '4) وثّق ما لاحظته وبلّغ الفريق اذا كانت المخاطرة عالية، '
            '5) لا تعتبر الحالة محلولة الا بعد التحقق الكامل. '
            'اذا ارسلت رقم التنبيه يمكنني اعطاؤك الخطوة التالية الدقيقة لهذا التنبيه.'
        ),
        (
            'Bonne question. En cas d alerte incident, suivez cette sequence : '
            '1) verifier la severite et la zone, '
            '2) ouvrir la surveillance en direct et confirmer le flux pendant 30-60 secondes, '
            '3) assigner le drone disponible le plus proche et un responsable, '
            '4) documenter vos observations et notifier l equipe si le risque est eleve, '
            '5) ne resoudre l alerte qu apres verification complete. '
            'Si vous donnez l id de l alerte, je peux proposer la prochaine action exacte pour ce cas.'
        ),
    )


def _assistant_is_action_request(q):
    action_phrases = [
        'what should i do',
        'what do i do',
        'what now',
        'next step',
        'what is the next step',
        'how should i handle',
        'how do i handle',
        'what is the procedure',
        'how to respond',
        'help me handle',
        'شنو نعمل',
        'ماذا افعل',
        'كيف اتصرف',
        'comment faire',
        'que faire',
        'prochaine etape',
    ]
    return any(phrase in q for phrase in action_phrases)


def _assistant_system_prompt(lang):
    return tr(
        lang,
        (
            'You are an advanced conversational AI assistant similar to ChatGPT. '
            'Your goal is to understand the user intent deeply and respond in a natural, human-like way. '
            'Do not rely on keywords only; always interpret meaning. '
            'If the user is vague or unclear, ask clarifying questions before answering. '
            'Give detailed, thoughtful responses instead of short, rigid ones. '
            'Explain concepts, give examples, and guide step-by-step when useful. '
            'Maintain a conversational tone like talking to a real person. '
            'Adapt tone to the situation (casual, technical, friendly). '
            'Before answering, think about what the user really wants. '
            'If multiple interpretations exist, mention them or ask for clarification. '
            'Do not assume too quickly. '
            'You are not limited to predefined commands and can handle broad topics. '
            'If you do not know something, say so honestly and suggest alternatives. '
            'Avoid robotic, repetitive, or template-like responses. '
            'Do not ignore parts of the user question. '
            'Use DroneSec alert/drone context when relevant and accurate. '
            'When operational counts or alert details are provided in context, treat them as authoritative and cite them clearly. '
            'Do not claim you lack details if those details are present in system context.'
        ),
        (
            'انت مساعد ذكاء اصطناعي متقدم وتحادثي شبيه ب ChatGPT. '
            'افهم نية المستخدم بعمق ورد بطريقة طبيعية مثل البشر. '
            'لا تعتمد فقط على الكلمات المفتاحية بل على المعنى. '
            'اذا كان الطلب غامضا فاسال اسئلة توضيحية قبل الاجابة. '
            'اعط اجابات مفصلة ومدروسة مع شرح وامثلة عند الحاجة. '
            'غيّر نبرة الحديث حسب السياق، وتجنب الردود الجامدة او المتكررة.'
        ),
        (
            'Vous etes un assistant conversationnel IA avance, proche de ChatGPT. '
            'Comprenez l intention en profondeur et repondez de facon naturelle et humaine. '
            'N utilisez pas seulement des mots-cles; interpretez le sens. '
            'Si la demande est floue, posez des questions de clarification avant de repondre. '
            'Donnez des reponses detaillees, expliquees, avec exemples si utile, et evitez le ton robotique.'
        ),
    )


def _assistant_is_vague_query(q):
    if not q:
        return True
    meaningful_tokens = [token for token in re.split(r'\s+', q) if token]
    if len(meaningful_tokens) <= 3:
        return True
    vague_phrases = {
        'help', 'i need help', 'what now', 'not working', 'issue', 'problem', 'can you help',
        'ساعدني', 'مساعدة', 'مو شغال', 'مش شغال', 'aide moi', 'besoin d aide'
    }
    return q.strip() in vague_phrases


def _assistant_clarifying_reply(lang):
    return tr(
        lang,
        (
            'I can help, and I want to give you a precise answer. '
            'Can you share three details: what happened, where it happened (zone/drone), and how urgent it feels? '
            'Once you send that, I will give you a concrete step-by-step plan.'
        ),
        (
            'اقدر اساعدك، وابي اعطيك جواب دقيق. '
            'بس اعطني 3 تفاصيل: ماذا حدث، اين حدث (المنطقة او الطائرة)، ومدى الاستعجال. '
            'بعدها اعطيك خطة واضحة خطوة بخطوة.'
        ),
        (
            'Je peux vous aider et je veux vous donner une reponse precise. '
            'Pouvez-vous donner trois details : ce qui s est passe, ou (zone/drone), et le niveau d urgence ? '
            'Ensuite, je vous donne un plan clair etape par etape.'
        ),
    )


def _assistant_sanitize_history(history):
    if not isinstance(history, list):
        return []

    max_items = max(0, int(getattr(settings, 'AI_ASSISTANT_MAX_HISTORY', 10) or 10))
    cleaned = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get('role') or '').strip().lower()
        if role in ('bot', 'assistant'):
            mapped_role = 'assistant'
        elif role == 'user':
            mapped_role = 'user'
        else:
            continue

        content = str(item.get('content') or '').strip()
        if not content:
            continue
        cleaned.append({
            'role': mapped_role,
            'content': content[:1200],
        })

    if max_items and len(cleaned) > max_items:
        return cleaned[-max_items:]
    return cleaned


def _assistant_db_history(user):
    max_items = max(0, int(getattr(settings, 'AI_ASSISTANT_MAX_HISTORY', 10) or 10))
    if max_items == 0:
        return []

    rows = list(
        AIAssistantMessage.objects
        .filter(user=user)
        .order_by('-created_at')[:max_items]
    )
    rows.reverse()

    return [
        {
            'role': row.role,
            'content': row.content,
        }
        for row in rows
    ]


def _assistant_store_db_history(user, history):
    cleaned = _assistant_sanitize_history(history)
    AIAssistantMessage.objects.filter(user=user).delete()
    AIAssistantMessage.objects.bulk_create([
        AIAssistantMessage(user=user, role=item['role'], content=item['content'])
        for item in cleaned
    ])
    return cleaned


def _assistant_is_local_provider(base_url):
    url = (base_url or '').lower()
    return ('localhost' in url) or ('127.0.0.1' in url)


def _assistant_llm_reply(query_text, lang, history):
    if not getattr(settings, 'AI_ASSISTANT_ENABLED', True):
        return '', 'disabled'

    base_url = str(getattr(settings, 'AI_ASSISTANT_BASE_URL', 'https://api.openai.com/v1') or 'https://api.openai.com/v1').rstrip('/')
    is_local_provider = _assistant_is_local_provider(base_url)
    api_key = str(getattr(settings, 'AI_ASSISTANT_API_KEY', '') or '').strip()
    if not api_key and not is_local_provider:
        return '', 'missing_api_key'

    model = str(getattr(settings, 'AI_ASSISTANT_MODEL', 'gpt-4o-mini') or 'gpt-4o-mini')
    temperature = float(getattr(settings, 'AI_ASSISTANT_TEMPERATURE', 0.65) or 0.65)
    timeout_seconds = max(5, int(getattr(settings, 'AI_ASSISTANT_TIMEOUT_SECONDS', 25) or 25))

    messages_payload = [
        {'role': 'system', 'content': _assistant_system_prompt(lang)},
        {'role': 'system', 'content': _assistant_operational_context(lang)},
        {'role': 'system', 'content': _assistant_db_overview_context(lang)},
        {'role': 'system', 'content': _assistant_detailed_alert_context(lang)},
        {'role': 'system', 'content': _assistant_alert_summary(lang)},
        *_assistant_sanitize_history(history),
        {'role': 'user', 'content': query_text[:1200]},
    ]

    headers = {
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    try:
        response = requests.post(
            f'{base_url}/chat/completions',
            headers=headers,
            json={
                'model': model,
                'messages': messages_payload,
                'temperature': temperature,
            },
            timeout=timeout_seconds,
        )
        if response.status_code == 401:
            return '', 'unauthorized'
        if response.status_code >= 400:
            return '', f'http_{response.status_code}'

        data = response.json()
        choice = (data.get('choices') or [{}])[0]
        message_obj = (choice or {}).get('message') or {}
        content = message_obj.get('content') or ''

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get('text') or block.get('content') or ''
                    if text:
                        parts.append(str(text))
            content = '\n'.join(parts)

        text = str(content).strip()[:3200]
        if not text:
            return '', 'empty_response'
        return text, ''
    except requests.RequestException:
        return '', 'network_error'
    except Exception:
        return '', 'unknown_error'


def _assistant_last_assistant_message(history):
    for item in reversed(_assistant_sanitize_history(history)):
        if item.get('role') == 'assistant':
            return str(item.get('content') or '').strip().lower()
    return ''


def _assistant_pick_non_repeating(options, history):
    if not options:
        return ''
    last_bot_text = _assistant_last_assistant_message(history)
    for option in options:
        if str(option).strip().lower() != last_bot_text:
            return option
    return random.choice(options)


def _assistant_smalltalk_reply(query_text, lang, history):
    q = (query_text or '').strip().lower()

    listen_tokens = ['listen', 'hear me', 'you there', 'اسمع', 'اسمعني', 'سمعني', 'écoute', 'ecoute']
    if any(token in q for token in listen_tokens):
        return _assistant_pick_non_repeating([
            tr(
                lang,
                'I am listening. Take your time and tell me what is going wrong, and I will help you think clearly through it.',
                'انا اسمعك. خذ وقتك واحكي لي وين المشكلة، وسنرتبها مع بعض خطوة خطوة.',
                'Je vous ecoute. Prenez votre temps et expliquez-moi ce qui ne va pas, puis on raisonne ensemble etape par etape.',
            ),
            tr(
                lang,
                'I hear you. Start with what happened first, then I can help you decide the next best move.',
                'انا معك. ابدا باول شيء صار، وبعدها اساعدك نحدد افضل خطوة تالية.',
                'Je vous entends. Commencez par ce qui s est passe en premier, puis je vous aide a choisir la meilleure suite.',
            ),
        ], history)

    if q in {'thanks', 'thank you', 'thx', 'شكرا', 'merci'}:
        return _assistant_pick_non_repeating([
            tr(lang, 'Anytime. Want me to review one alert with you now?', 'على الرحب. تحب نراجع تنبيه واحد الان؟', 'Avec plaisir. Voulez-vous qu on analyse une alerte maintenant ?'),
            tr(lang, 'You got it. If you want, send an alert id and I will break it down fast.', 'تم. اذا تحب، ارسل رقم تنبيه وانا احلله لك بسرعة.', 'Parfait. Si vous voulez, envoyez un id d alerte et je le decompose rapidement.'),
        ], history)

    if 'who are you' in q or 'are you real' in q or 'من انت' in q or 'qui es tu' in q:
        return tr(
            lang,
            'I am your DroneSec assistant. I am software, but I will talk with you naturally and focus on helping you make good decisions quickly.',
            'انا مساعدك داخل DroneSec. صحيح اني برنامج، لكن اتكلم معك بشكل طبيعي وهدفي اساعدك تاخذ قرار صح بسرعة.',
            'Je suis votre assistant DroneSec. Je suis un logiciel, mais je parle naturellement et je me concentre sur des decisions utiles et rapides.',
        )

    return ''


def _assistant_reply_for_query(query_text, lang, history=None):
    history = history or []
    query = (query_text or '').strip()
    q = query.lower()

    if not query:
        return tr(
            lang,
            'Ask me about an alert, drone status, or where to find a page in DroneSec.',
            'اسالني عن تنبيه، حالة طائرة، او مكان اي صفحة داخل DroneSec.',
            'Demandez moi une alerte, le statut drone, ou ou trouver une page dans DroneSec.',
        )

    smalltalk = _assistant_smalltalk_reply(query, lang, history)
    if smalltalk:
        return smalltalk

    if _assistant_is_vague_query(q):
        return _assistant_clarifying_reply(lang)

    mentions_incident = any(token in q for token in ['incident', 'inciden', 'alert', 'critical', 'unresolved'])
    if _assistant_is_action_request(q) and mentions_incident:
        return _assistant_incident_action_guide(lang)

    if q in {'hi', 'hello', 'hey', 'yo', 'salam', 'salut', 'bonjour', 'مرحبا', 'اهلا', 'أهلا'}:
        return tr(
            lang,
            (
                'Hey, glad you are here. Tell me what you are dealing with and I will think it through with you. '
                'If you want, I can start by summarizing unresolved alerts or checking drone status first.'
            ),
            (
                'اهلا، سعيد بوجودك. احكي لي ما المشكلة وسافكر فيها معك خطوة بخطوة. '
                'اذا تحب، ابدا لك بملخص التنبيهات غير المحلولة او حالة الطائرات.'
            ),
            (
                'Salut, content de vous aider. Dites-moi votre situation et je vais la traiter avec vous etape par etape. '
                'Je peux commencer par un resume des alertes non resolues ou du statut des drones.'
            ),
        )

    alert_id_match = re.search(r'(?:alert\s*#?\s*|#)(\d+)', q)
    if alert_id_match:
        alert_id = int(alert_id_match.group(1))
        alert = Alert.objects.select_related('drone').filter(id=alert_id).first()
        if not alert:
            return tr(
                lang,
                f'I could not find alert #{alert_id}.',
                f'لم اعثر على التنبيه رقم #{alert_id}.',
                f"Je n ai pas trouve l alerte #{alert_id}.",
            )

        status = tr(lang, 'Resolved' if alert.is_resolved else 'Unresolved', 'محلول' if alert.is_resolved else 'غير محلول', 'Resolue' if alert.is_resolved else 'Non resolue')
        drone_name = alert.drone.name if alert.drone else tr(lang, 'System', 'النظام', 'Systeme')
        summary = tr(
            lang,
            f"Alert #{alert.id}: {alert.title} | Severity: {alert.severity} | Status: {status} | Drone: {drone_name}.",
            f"التنبيه #{alert.id}: {alert.title} | الشدة: {alert.severity} | الحالة: {status} | الطائرة: {drone_name}.",
            f"Alerte #{alert.id} : {alert.title} | Severite : {alert.severity} | Statut : {status} | Drone : {drone_name}.",
        )
        return summary + "\n" + _assistant_alert_action_text(alert, lang)

    if 'alert' in q or 'critical' in q or 'unresolved' in q or 'incident' in q:
        return _assistant_pick_non_repeating([
            _assistant_alert_summary(lang),
            _assistant_incident_action_guide(lang),
        ], history)

    if any(token in q for token in ['drone', 'drones', 'battery', 'طائرة', 'الطائرات', 'بطارية', 'drone', 'drones']):
        total_drones = Drone.objects.count()
        online_count = Drone.objects.filter(status__in=['online', 'patrolling']).count()
        offline_count = Drone.objects.filter(status='offline').count()
        charging_count = Drone.objects.filter(status='charging').count()
        return tr(
            lang,
            f"You currently have {total_drones} drones in total. Status now: online/patrolling {online_count}, charging {charging_count}, offline {offline_count}.",
            f"لديكم حاليا {total_drones} طائرة بالمجموع. الحالة الان: متصلة/في دورية {online_count}، قيد الشحن {charging_count}، غير متصلة {offline_count}.",
            f"Vous avez actuellement {total_drones} drones au total. Statut actuel : en ligne/patrouille {online_count}, en charge {charging_count}, hors ligne {offline_count}.",
        )

    if looks_for_agents and looks_for_presence:
        return _assistant_agent_presence_reply(lang)

    page_hint = _assistant_page_hint(query, lang)
    if page_hint:
        return page_hint

    return _assistant_pick_non_repeating([
        tr(
            lang,
            (
                'I get what you are saying. Give me one concrete detail, like alert id, zone, or drone name, '
                'and I will give you a precise next step.'
            ),
            (
                'فهمت عليك. اعطني معلومة واحدة واضحة مثل رقم التنبيه او المنطقة او اسم الطائرة، '
                'وانا اعطيك خطوة تالية دقيقة.'
            ),
            (
                'Je vois ce que vous voulez dire. Donnez-moi un detail concret, comme id d alerte, zone ou nom du drone, '
                'et je vous donne la prochaine etape precise.'
            ),
        ),
        tr(
            lang,
            (
                'Understood. I can help you think this through like a teammate. '
                'Start with what happened first, and I will structure the response clearly.'
            ),
            (
                'واضح. اقدر افكر معك مثل زميل. '
                'ابدا باول شيء صار، وانا سارتب لك الرد بشكل واضح.'
            ),
            (
                'Compris. Je peux raisonner avec vous comme un collegue. '
                'Commencez par le debut et je structure une reponse claire.'
            ),
        ),
    ], history)


@login_required
@require_http_methods(['GET', 'POST'])
def ai_assistant_chat_api(request):
    if not request.user.can_access:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)

    if request.method == 'GET':
        return JsonResponse({
            'history': _assistant_db_history(request.user),
        })

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        payload = {}

    message = str(payload.get('message') or '').strip()[:600]
    if not message:
        return JsonResponse({'error': 'empty_message'}, status=400)

    client_history = payload.get('history') if isinstance(payload, dict) else []
    db_history = _assistant_db_history(request.user)
    history = db_history or _assistant_sanitize_history(client_history)
    lang = get_lang(request)

    direct_fact_reply = _assistant_direct_fact_reply(message, lang)
    if direct_fact_reply:
        updated_history = _assistant_store_db_history(request.user, history + [
            {'role': 'user', 'content': message},
            {'role': 'assistant', 'content': direct_fact_reply},
        ])
        return JsonResponse({
            'reply': direct_fact_reply,
            'source': 'db',
            'llm_error': '',
            'think_ms': random.randint(450, 900),
            'at': timezone.localtime(timezone.now()).strftime('%H:%M'),
            'history': updated_history,
        })

    reply, llm_error = _assistant_llm_reply(message, lang, history)
    source = 'llm'
    if not reply:
        source = 'fallback'
        if llm_error == 'unauthorized':
            fallback = _assistant_reply_for_query(message, lang, history)
            notice = tr(
                lang,
                'Quick heads-up: full AI mode is not connected because the provider rejected authentication. Check AI_ASSISTANT_API_KEY in .env, then restart the server.',
                'ملاحظة سريعة: وضع الذكاء الكامل غير متصل لان مزود الخدمة رفض المصادقة. تحقق من AI_ASSISTANT_API_KEY في .env ثم اعد تشغيل السيرفر.',
                'Info rapide : le mode IA complet n est pas connecte car le fournisseur a refuse l authentification. Verifiez AI_ASSISTANT_API_KEY dans .env puis redemarrez.',
            )
            reply = f'{notice}\n\n{fallback}'
        elif llm_error == 'http_429':
            fallback = _assistant_reply_for_query(message, lang, history)
            notice = tr(
                lang,
                'Quick heads-up: the AI provider returned rate/quota limit (429), so I am temporarily using local fallback mode. Check your API usage/billing and try again in a moment.',
                'ملاحظة سريعة: مزود الذكاء اعاد خطا حد الاستخدام/الحصة (429)، لذلك استخدم وضع بديل مؤقت. تحقق من الفوترة او الحصة ثم اعد المحاولة بعد قليل.',
                'Info rapide : le fournisseur IA a retourne une limite de quota/debit (429), donc je passe temporairement en mode local. Verifiez la facturation/le quota puis reessayez.',
            )
            reply = f'{notice}\n\n{fallback}'
        elif llm_error.startswith('http_') or llm_error in {'network_error', 'unknown_error', 'empty_response'}:
            fallback = _assistant_reply_for_query(message, lang, history)
            notice = tr(
                lang,
                'Quick heads-up: full AI mode is temporarily unavailable, so I am answering from fallback mode for now.',
                'ملاحظة سريعة: وضع الذكاء الكامل غير متاح مؤقتا، لذلك ارد حاليا من الوضع البديل.',
                'Info rapide : le mode IA complet est temporairement indisponible, donc je reponds en mode de secours pour le moment.',
            )
            reply = f'{notice}\n\n{fallback}'
        else:
            reply = _assistant_reply_for_query(message, lang, history)

    updated_history = _assistant_store_db_history(request.user, history + [
        {'role': 'user', 'content': message},
        {'role': 'assistant', 'content': reply},
    ])

    return JsonResponse({
        'reply': reply,
        'source': source,
        'llm_error': llm_error,
        'think_ms': random.randint(900, 1700) if source == 'llm' else random.randint(550, 1100),
        'at': timezone.localtime(timezone.now()).strftime('%H:%M'),
        'history': updated_history,
    })


# ========== HOME & DASHBOARD VIEWS ==========
def home(request):
    """Public home/landing page - redirect to dashboard if authenticated"""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    lang = get_lang(request)
    context = {}

    if request.method == 'POST':
        form_type = (request.POST.get('form_type') or '').strip()
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

        def _error(message, status=400):
            context['contact_error'] = message
            if is_ajax:
                return JsonResponse({'ok': False, 'message': message}, status=status)
            return render(request, 'home.html', context)

        if form_type == 'contact_request_code':
            sender_email = (request.POST.get('email') or '').strip().lower()
            if not sender_email:
                return _error(
                    tr(
                        lang,
                        'Please enter your email first.',
                        'يرجى ادخال بريدك الالكتروني اولا.',
                        'Veuillez saisir votre e-mail d abord.',
                    ),
                    status=400,
                )

            try:
                validate_email(sender_email)
            except ValidationError:
                return _error(
                    tr(
                        lang,
                        'Please enter a valid email address (example: name@example.com).',
                        'يرجى ادخال بريد الكتروني صحيح (مثال: name@example.com).',
                        'Veuillez saisir un e-mail valide (exemple : nom@exemple.com).',
                    ),
                    status=400,
                )

            if getattr(settings, 'EMAIL_BACKEND', '') == 'django.core.mail.backends.console.EmailBackend':
                return _error(
                    tr(
                        lang,
                        'Contact email is not configured yet. Please set SMTP credentials in .env first.',
                        'بريد التواصل غير مهيأ بعد. يرجى اضافة بيانات SMTP في ملف .env اولا.',
                        "L'e-mail de contact n'est pas encore configure. Veuillez d'abord definir SMTP dans .env.",
                    ),
                    status=503,
                )

            verification_code = f"{random.randint(100000, 999999)}"
            expiry_epoch = int(time.time()) + 600

            request.session['contact_verify_email'] = sender_email
            request.session['contact_verify_code'] = verification_code
            request.session['contact_verify_expiry'] = expiry_epoch
            request.session['contact_verify_attempts'] = 0
            request.session['contact_verified_email'] = ''

            verification_subject = tr(
                lang,
                'DroneSec Email Verification Code',
                'رمز التحقق من البريد - DroneSec',
                'Code de verification e-mail - DroneSec',
            )
            verification_body = tr(
                lang,
                (
                    f'Your DroneSec verification code is: {verification_code}\n\n'
                    'This code expires in 10 minutes.'
                ),
                (
                    f'رمز التحقق الخاص بك في DroneSec هو: {verification_code}\n\n'
                    'تنتهي صلاحية هذا الرمز خلال 10 دقائق.'
                ),
                (
                    f'Votre code de verification DroneSec est : {verification_code}\n\n'
                    'Ce code expire dans 10 minutes.'
                ),
            )

            try:
                send_mail(
                    verification_subject,
                    verification_body,
                    settings.DEFAULT_FROM_EMAIL,
                    [sender_email],
                    fail_silently=False,
                )
                success_text = tr(
                    lang,
                    'Verification code sent. Please check your inbox and enter the code.',
                    'تم ارسال رمز التحقق. يرجى تفقد بريدك وادخال الرمز.',
                    'Code de verification envoye. Verifiez votre boite mail puis entrez le code.',
                )
                if is_ajax:
                    return JsonResponse({'ok': True, 'message': success_text})
                context['contact_success'] = success_text
                return render(request, 'home.html', context)
            except Exception:
                return _error(
                    tr(
                        lang,
                        'Could not send verification code right now. Please try again in a moment.',
                        'تعذر ارسال رمز التحقق حاليا. يرجى المحاولة بعد قليل.',
                        "Impossible d'envoyer le code de verification pour le moment. Veuillez reessayer.",
                    ),
                    status=500,
                )

        if form_type == 'contact_verify_code':
            sender_email = (request.POST.get('email') or '').strip().lower()
            verification_code = (request.POST.get('verification_code') or '').strip()

            stored_email = (request.session.get('contact_verify_email') or '').strip().lower()
            stored_code = str(request.session.get('contact_verify_code') or '').strip()
            expiry_epoch = int(request.session.get('contact_verify_expiry') or 0)
            attempts = int(request.session.get('contact_verify_attempts') or 0)

            if not sender_email or not verification_code:
                return _error(
                    tr(
                        lang,
                        'Please enter the verification code.',
                        'يرجى ادخال رمز التحقق.',
                        'Veuillez saisir le code de verification.',
                    ),
                    status=400,
                )

            if attempts >= 5:
                return _error(
                    tr(
                        lang,
                        'Too many failed attempts. Request a new verification code.',
                        'عدد كبير من المحاولات الفاشلة. اطلب رمز تحقق جديد.',
                        'Trop de tentatives echouees. Demandez un nouveau code.',
                    ),
                    status=429,
                )

            if not stored_email or not stored_code or sender_email != stored_email:
                return _error(
                    tr(
                        lang,
                        'Please request a new verification code for this email.',
                        'يرجى طلب رمز تحقق جديد لهذا البريد.',
                        'Veuillez demander un nouveau code pour cet e-mail.',
                    ),
                    status=400,
                )

            if int(time.time()) > expiry_epoch:
                return _error(
                    tr(
                        lang,
                        'Verification code expired. Request a new one.',
                        'انتهت صلاحية رمز التحقق. اطلب رمزا جديدا.',
                        'Le code de verification a expire. Demandez-en un nouveau.',
                    ),
                    status=400,
                )

            if verification_code != stored_code:
                request.session['contact_verify_attempts'] = attempts + 1
                return _error(
                    tr(
                        lang,
                        'Invalid verification code. Please try again.',
                        'رمز التحقق غير صحيح. يرجى المحاولة مرة اخرى.',
                        'Code de verification invalide. Veuillez reessayer.',
                    ),
                    status=400,
                )

            request.session['contact_verified_email'] = sender_email
            request.session['contact_verify_code'] = ''
            request.session['contact_verify_attempts'] = 0
            request.session['contact_verify_expiry'] = 0

            success_text = tr(
                lang,
                'Email verified successfully. You can now send your message.',
                'تم التحقق من البريد بنجاح. يمكنك الآن ارسال رسالتك.',
                'E-mail verifie avec succes. Vous pouvez maintenant envoyer votre message.',
            )
            if is_ajax:
                return JsonResponse({'ok': True, 'message': success_text})
            context['contact_success'] = success_text
            return render(request, 'home.html', context)

        if form_type == 'contact':
            name = (request.POST.get('name') or '').strip()
            sender_email = (request.POST.get('email') or '').strip().lower()
            message_text = (request.POST.get('message') or '').strip()

            context.update({
                'contact_name': name,
                'contact_email': sender_email,
                'contact_message': message_text,
            })

            if not name or not sender_email or not message_text:
                return _error(
                    tr(
                        lang,
                        'Please fill in your name, email, and message.',
                        'يرجى تعبئة الاسم والبريد الالكتروني والرسالة.',
                        'Veuillez remplir votre nom, e-mail et message.',
                    ),
                    status=400,
                )

            try:
                validate_email(sender_email)
            except ValidationError:
                return _error(
                    tr(
                        lang,
                        'Please enter a valid email address (example: name@example.com).',
                        'يرجى ادخال بريد الكتروني صحيح (مثال: name@example.com).',
                        'Veuillez saisir un e-mail valide (exemple : nom@exemple.com).',
                    ),
                    status=400,
                )

            verified_email = (request.session.get('contact_verified_email') or '').strip().lower()
            if verified_email != sender_email:
                return _error(
                    tr(
                        lang,
                        'Please verify your email before sending the message.',
                        'يرجى التحقق من بريدك الالكتروني قبل ارسال الرسالة.',
                        "Veuillez verifier votre e-mail avant d'envoyer le message.",
                    ),
                    status=403,
                )

            if getattr(settings, 'EMAIL_BACKEND', '') == 'django.core.mail.backends.console.EmailBackend':
                return _error(
                    tr(
                        lang,
                        'Contact email is not configured yet. Please set SMTP credentials in .env first.',
                        'بريد التواصل غير مهيأ بعد. يرجى اضافة بيانات SMTP في ملف .env اولا.',
                        "L'e-mail de contact n'est pas encore configure. Veuillez d'abord definir SMTP dans .env.",
                    ),
                    status=503,
                )

            subject = f'DroneSec Contact Message from {name}'
            body = (
                'New contact message from DroneSec landing page.\n\n'
                f'Name: {name}\n'
                f'Email: {sender_email}\n\n'
                'Message:\n'
                f'{message_text}\n'
            )
            try:
                send_mail(
                    subject,
                    body,
                    settings.DEFAULT_FROM_EMAIL,
                    [settings.CONTACT_RECEIVER_EMAIL],
                    fail_silently=False,
                )
                request.session['contact_verified_email'] = ''
                request.session['contact_verify_email'] = ''
                request.session['contact_verify_code'] = ''
                request.session['contact_verify_expiry'] = 0
                request.session['contact_verify_attempts'] = 0

                success_text = tr(
                    lang,
                    'Your message was sent successfully. We will get back to you soon.',
                    'تم ارسال رسالتك بنجاح. سنعود اليك في اقرب وقت.',
                    'Votre message a ete envoye avec succes. Nous vous repondrons bientot.',
                )
                context['contact_success'] = success_text
                context.update({
                    'contact_name': '',
                    'contact_email': '',
                    'contact_message': '',
                })
                if is_ajax:
                    return JsonResponse({'ok': True, 'message': success_text})
            except Exception:
                return _error(
                    tr(
                        lang,
                        'Message could not be sent right now. Please try again in a moment.',
                        'تعذر ارسال الرسالة حاليا. يرجى المحاولة بعد قليل.',
                        "Le message n'a pas pu etre envoye pour le moment. Veuillez reessayer.",
                    ),
                    status=500,
                )

    return render(request, 'home.html', context)


@login_required
def dashboard_index(request):
    user = request.user
    if not user.can_access:
        return render(request, 'core/dashboard/pending.html')

    drones = Drone.objects.all()
    recent_alerts = Alert.objects.filter(is_resolved=False).order_by('-created_at')[:8]
    unread_count = Alert.objects.filter(is_read=False, is_resolved=False).count()

    context = {
        'drones': drones,
        'drones_online': drones.filter(status__in=['online', 'patrolling']).count(),
        'drones_offline': drones.filter(status='offline').count(),
        'drones_charging': drones.filter(status='charging').count(),
        'total_drones': drones.count(),
        'total_alerts': Alert.objects.count(),
        'unresolved_alerts': Alert.objects.filter(is_resolved=False).count(),
        'critical_alerts': Alert.objects.filter(severity='critical', is_resolved=False).count(),
        'recent_alerts': recent_alerts,
        'unread_count': unread_count,
        'now': timezone.now(),
    }

    if user.is_admin:
        context['pending_agents'] = CustomUser.objects.filter(
            role='agent', is_approved=False, is_active=True).count()
        context['total_agents'] = CustomUser.objects.filter(role='agent', is_approved=True).count()

    return render(request, 'core/dashboard/index.html', context)


def _clear_register_verification_session(request):
    for key in [
        REGISTER_PENDING_DATA_KEY,
        REGISTER_VERIFY_EMAIL_KEY,
        REGISTER_VERIFY_CODE_KEY,
        REGISTER_VERIFY_EXPIRY_KEY,
        REGISTER_VERIFY_ATTEMPTS_KEY,
    ]:
        request.session.pop(key, None)


def _log_security_event(event_type, message, severity='info', source='system', user=None, drone=None, alert=None, details=None):
    payload = {}
    if isinstance(details, dict):
        for key, value in details.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
            else:
                payload[key] = str(value)
    elif details is not None:
        payload = {'value': str(details)}

    try:
        SecuritySystemLog.objects.create(
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            details=payload,
            user=user,
            drone=drone,
            alert=alert,
        )
    except Exception:
        # Logging should never break the main user flow.
        return


def _verify_phone_number_exists(phone_e164, phone_country, lang):
    return True, ''


def _send_register_email_code(request, recipient_email, lang):
    if getattr(settings, 'EMAIL_BACKEND', '') == 'django.core.mail.backends.console.EmailBackend':
        raise ValueError(tr(
            lang,
            'Email verification requires SMTP setup. Configure email settings in .env first.',
            'التحقق من البريد يتطلب اعداد SMTP. يرجى ضبط اعدادات البريد في ملف .env اولا.',
            "La verification e-mail exige une configuration SMTP. Configurez d'abord les parametres e-mail dans .env.",
        ))

    verification_code = f"{random.randint(100000, 999999)}"
    expiry_epoch = int(time.time()) + 600

    request.session[REGISTER_VERIFY_EMAIL_KEY] = recipient_email
    request.session[REGISTER_VERIFY_CODE_KEY] = verification_code
    request.session[REGISTER_VERIFY_EXPIRY_KEY] = expiry_epoch
    request.session[REGISTER_VERIFY_ATTEMPTS_KEY] = 0

    subject = tr(
        lang,
        'DroneSec Request Access Email Verification',
        'التحقق من بريد طلب الوصول - DroneSec',
        'Verification e-mail de demande d acces - DroneSec',
    )
    body = tr(
        lang,
        (
            f'Your DroneSec verification code is: {verification_code}\n\n'
            'Enter this code to complete your request access registration.\n'
            'This code expires in 10 minutes.'
        ),
        (
            f'رمز التحقق الخاص بك في DroneSec هو: {verification_code}\n\n'
            'ادخل هذا الرمز لاكمال تسجيل طلب الوصول.\n'
            'تنتهي صلاحية الرمز خلال 10 دقائق.'
        ),
        (
            f'Votre code de verification DroneSec est : {verification_code}\n\n'
            'Entrez ce code pour terminer votre demande d acces.\n'
            'Ce code expire dans 10 minutes.'
        ),
    )

    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [recipient_email],
        fail_silently=False,
    )


def _create_agent_from_pending_data(pending_data, lang):
    user = CustomUser(
        username=pending_data['username'],
        first_name=pending_data.get('first_name', ''),
        last_name=pending_data.get('last_name', ''),
        email=pending_data['email'],
        department=pending_data.get('department', ''),
        phone=pending_data.get('phone', ''),
        role='agent',
        is_approved=False,
        is_active=True,
        email_verified=True,
        email_token=str(uuid.uuid4()),
        language=lang if lang in {'en', 'ar', 'fr'} else 'en',
    )
    user.password = pending_data['password_hash']
    user.save()
    return user


# ========== USER/AUTH VIEWS ==========
def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    lang = get_lang(request)
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST, language=lang)
        if form.is_valid():
            user = form.get_user()
            if not user.can_access and not user.is_admin:
                lang = getattr(user, 'language', get_lang(request))
                messages.error(request, tr(
                    lang,
                    "Your account is pending admin approval.",
                    "حسابك بانتظار موافقة المشرف.",
                    "Votre compte est en attente d'approbation administrateur.",
                ))
                return render(request, 'core/users/login.html', {'form': form})
            login(request, user)
            request.session['preferred_language'] = user.language
            if not form.cleaned_data.get('remember_me'):
                request.session.set_expiry(0)
            user.last_seen = timezone.now()
            user.save(update_fields=['last_seen'])
            _log_security_event(
                'user_login',
                f"User login: {user.username} ({user.role})",
                severity='info',
                source='auth',
                user=user,
                details={
                    'role': user.role,
                    'auth_method': 'password',
                    'logged_in_at': timezone.now().isoformat(),
                },
            )
            welcome = tr(
                user.language,
                f"Welcome back, {user.first_name or user.username}!",
                f"مرحبا بعودتك، {user.first_name or user.username}!",
                f"Bon retour, {user.first_name or user.username} !",
            )
            messages.success(request, welcome)
            return redirect(request.GET.get('next', 'core:dashboard'))
    else:
        form = LoginForm(language=lang)

    return render(request, 'core/users/login.html', {
        'form': form,
        'recaptcha_key': settings.RECAPTCHA_PUBLIC_KEY,
        'google_client_id': settings.GOOGLE_CLIENT_ID,
    })


def register_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    lang = get_lang(request)
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'resend_email_code':
            pending_data = request.session.get(REGISTER_PENDING_DATA_KEY) or {}
            recipient_email = (pending_data.get('email') or '').strip().lower()
            if not pending_data or not recipient_email:
                messages.error(request, tr(
                    lang,
                    'No pending registration was found. Please submit the form again.',
                    'لم يتم العثور على طلب تسجيل معلق. يرجى ارسال النموذج مرة اخرى.',
                    'Aucune inscription en attente trouvee. Veuillez soumettre le formulaire a nouveau.',
                ))
                return redirect('core:register')

            try:
                _send_register_email_code(request, recipient_email, lang)
                messages.info(request, tr(
                    lang,
                    'A new verification code was sent to your email.',
                    'تم ارسال رمز تحقق جديد الى بريدك.',
                    'Un nouveau code de verification a ete envoye a votre e-mail.',
                ))
            except ValueError as exc:
                messages.error(request, str(exc))
            except Exception:
                messages.error(request, tr(
                    lang,
                    'Could not send verification code right now. Please try again in a moment.',
                    'تعذر ارسال رمز التحقق حاليا. يرجى المحاولة بعد قليل.',
                    "Impossible d'envoyer le code de verification pour le moment. Veuillez reessayer.",
                ))
            return redirect('core:register')

        if action == 'restart_register':
            _clear_register_verification_session(request)
            messages.info(request, tr(
                lang,
                'Request access process was reset. Please submit your details again.',
                'تمت اعادة تعيين طلب الوصول. يرجى ادخال بياناتك مرة اخرى.',
                "Le processus de demande d'acces a ete reinitialise. Veuillez soumettre vos informations a nouveau.",
            ))
            return redirect('core:register')

        form = RegisterForm(request.POST, language=lang)
        if form.is_valid():
            phone_country = form.cleaned_data.get('phone_country')
            phone_e164 = form.cleaned_data.get('phone')

            phone_ok, phone_error = _verify_phone_number_exists(phone_e164, phone_country, lang)
            if not phone_ok:
                form.add_error('phone', phone_error)
            else:
                pending_data = {
                    'username': form.cleaned_data['username'],
                    'first_name': form.cleaned_data['first_name'],
                    'last_name': form.cleaned_data['last_name'],
                    'email': form.cleaned_data['email'].strip().lower(),
                    'department': form.cleaned_data.get('department', '').strip(),
                    'phone': phone_e164,
                    'phone_country': phone_country,
                    'password_hash': make_password(form.cleaned_data['password1']),
                }
                request.session[REGISTER_PENDING_DATA_KEY] = pending_data

                try:
                    _send_register_email_code(request, pending_data['email'], lang)
                    messages.info(request, tr(
                        lang,
                        'Verification code sent to your email. Enter it below to complete request access.',
                        'تم ارسال رمز التحقق الى بريدك. ادخله بالاسفل لاكمال طلب الوصول.',
                        'Code de verification envoye a votre e-mail. Saisissez-le ci-dessous pour terminer la demande d acces.',
                    ))
                    return redirect('core:register')
                except ValueError as exc:
                    form.add_error('email', str(exc))
                except Exception:
                    form.add_error('email', tr(
                        lang,
                        'Could not send verification code right now. Please try again in a moment.',
                        'تعذر ارسال رمز التحقق حاليا. يرجى المحاولة بعد قليل.',
                        "Impossible d'envoyer le code de verification pour le moment. Veuillez reessayer.",
                    ))
    else:
        form = RegisterForm(language=lang)

    pending_email = (request.session.get(REGISTER_VERIFY_EMAIL_KEY) or '').strip()

    return render(request, 'core/users/register.html', {
        'form': form,
        'recaptcha_key': settings.RECAPTCHA_PUBLIC_KEY,
        'show_email_verification': bool(pending_email),
        'pending_email': pending_email,
    })


@require_POST
def register_verify_email_code(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    lang = get_lang(request)
    verification_code = (request.POST.get('email_verification_code') or '').strip()
    pending_data = request.session.get(REGISTER_PENDING_DATA_KEY) or {}
    stored_email = (request.session.get(REGISTER_VERIFY_EMAIL_KEY) or '').strip().lower()
    stored_code = str(request.session.get(REGISTER_VERIFY_CODE_KEY) or '').strip()
    expiry_epoch = int(request.session.get(REGISTER_VERIFY_EXPIRY_KEY) or 0)
    attempts = int(request.session.get(REGISTER_VERIFY_ATTEMPTS_KEY) or 0)

    if not pending_data or not stored_email or not stored_code:
        messages.error(request, tr(
            lang,
            'No pending email verification found. Please submit request access form again.',
            'لم يتم العثور على تحقق بريد معلق. يرجى ارسال نموذج طلب الوصول مرة اخرى.',
            "Aucune verification e-mail en attente. Veuillez soumettre le formulaire de demande d'acces a nouveau.",
        ))
        _clear_register_verification_session(request)
        return redirect('core:register')

    if not verification_code:
        messages.error(request, tr(
            lang,
            'Please enter the email verification code.',
            'يرجى ادخال رمز التحقق من البريد.',
            'Veuillez saisir le code de verification e-mail.',
        ))
        return redirect('core:register')

    if attempts >= 5:
        messages.error(request, tr(
            lang,
            'Too many failed attempts. Request a new verification code.',
            'عدد كبير من المحاولات الفاشلة. اطلب رمز تحقق جديد.',
            'Trop de tentatives echouees. Demandez un nouveau code de verification.',
        ))
        return redirect('core:register')

    if int(time.time()) > expiry_epoch:
        messages.error(request, tr(
            lang,
            'Verification code expired. Request a new one.',
            'انتهت صلاحية رمز التحقق. اطلب رمزا جديدا.',
            'Le code de verification a expire. Demandez-en un nouveau.',
        ))
        return redirect('core:register')

    if verification_code != stored_code:
        request.session[REGISTER_VERIFY_ATTEMPTS_KEY] = attempts + 1
        messages.error(request, tr(
            lang,
            'Invalid verification code. Please try again.',
            'رمز التحقق غير صحيح. يرجى المحاولة مرة اخرى.',
            'Code de verification invalide. Veuillez reessayer.',
        ))
        return redirect('core:register')

    pending_username = (pending_data.get('username') or '').strip()
    pending_email = (pending_data.get('email') or '').strip().lower()
    if not pending_username or not pending_email or pending_email != stored_email:
        messages.error(request, tr(
            lang,
            'Pending registration data is invalid. Please submit the form again.',
            'بيانات التسجيل المعلقة غير صالحة. يرجى ارسال النموذج مرة اخرى.',
            "Les donnees d'inscription en attente sont invalides. Veuillez soumettre le formulaire a nouveau.",
        ))
        _clear_register_verification_session(request)
        return redirect('core:register')

    if CustomUser.objects.filter(username=pending_username).exists():
        messages.error(request, tr(
            lang,
            'This username is no longer available. Please submit request access again.',
            'اسم المستخدم هذا لم يعد متاحا. يرجى ارسال طلب الوصول من جديد.',
            "Ce nom d'utilisateur n'est plus disponible. Veuillez refaire la demande d'acces.",
        ))
        _clear_register_verification_session(request)
        return redirect('core:register')

    if CustomUser.objects.filter(email__iexact=pending_email).exists():
        messages.error(request, tr(
            lang,
            'An account with this email already exists.',
            'يوجد حساب بهذا البريد الالكتروني بالفعل.',
            'Un compte avec cet e-mail existe deja.',
        ))
        _clear_register_verification_session(request)
        return redirect('core:register')

    try:
        user = _create_agent_from_pending_data(pending_data, lang)
    except Exception:
        messages.error(request, tr(
            lang,
            'Could not complete registration right now. Please try again.',
            'تعذر اكمال التسجيل حاليا. يرجى المحاولة مرة اخرى.',
            "Impossible de terminer l'inscription pour le moment. Veuillez reessayer.",
        ))
        return redirect('core:register')

    _clear_register_verification_session(request)

    admins = CustomUser.objects.filter(role='admin', is_active=True)
    for admin in admins:
        send_mail(
            'New Agent Registration – DroneSec',
            f'A new agent {user.get_full_name()} ({user.email}) is waiting for approval.\n'
            f'Login to admin panel to approve them.',
            settings.DEFAULT_FROM_EMAIL,
            [admin.email],
            fail_silently=True,
        )

    messages.success(request, tr(
        lang,
        "Registration successful! Your account is pending admin approval. You'll be notified by email.",
        "تم التسجيل بنجاح! حسابك بانتظار موافقة المشرف وسيصلك إشعار عبر البريد.",
        "Inscription reussie ! Votre compte est en attente d'approbation administrateur. Vous serez notifie par e-mail.",
    ), extra_tags='signup-success')
    return redirect('core:login')


def logout_view(request):
    lang = get_lang(request)
    if request.user.is_authenticated:
        current_user = request.user
        if getattr(current_user, 'language', None):
            lang = current_user.language
        _log_security_event(
            'user_logout',
            f"User logout: {current_user.username} ({current_user.role})",
            severity='info',
            source='auth',
            user=current_user,
            details={
                'role': current_user.role,
                'logged_out_at': timezone.now().isoformat(),
            },
        )
        AIAssistantMessage.objects.filter(user=current_user).delete()
    logout(request)
    request.session['preferred_language'] = lang
    messages.info(request, tr(
        lang,
        "You have been logged out.",
        "تم تسجيل خروجك.",
        "Vous avez ete deconnecte.",
    ))
    return redirect('core:login')


def google_login(request):
    """Redirect to Google OAuth2."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_REDIRECT_URI:
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            'Google login is not configured. Please contact the administrator.',
            'تسجيل الدخول عبر Google غير مهيأ. يرجى التواصل مع المشرف.',
            'La connexion Google n est pas configuree. Veuillez contacter l administrateur.',
        ))
        return redirect('core:login')

    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={settings.GOOGLE_REDIRECT_URI}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        "&access_type=offline"
    )
    return redirect(google_auth_url)


def google_callback(request):
    """Handle Google OAuth2 callback."""
    code = request.GET.get('code')
    lang = get_lang(request)
    if not code:
        messages.error(request, tr(
            lang,
            "Google login failed.",
            "فشل تسجيل الدخول عبر Google.",
            "La connexion Google a echoue.",
        ))
        return redirect('core:login')

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET or not settings.GOOGLE_REDIRECT_URI:
        messages.error(request, tr(
            lang,
            'Google login is not configured. Please contact the administrator.',
            'تسجيل الدخول عبر Google غير مهيأ. يرجى التواصل مع المشرف.',
            'La connexion Google n est pas configuree. Veuillez contacter l administrateur.',
        ))
        return redirect('core:login')

    try:
        token_resp = requests.post('https://oauth2.googleapis.com/token', data={
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': settings.GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code',
        }, timeout=10).json()

        access_token = token_resp.get('access_token')
        user_info = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10
        ).json()

        google_id = user_info.get('id')
        email = user_info.get('email')
        first_name = user_info.get('given_name', '')
        last_name = user_info.get('family_name', '')

        user = CustomUser.objects.filter(google_id=google_id).first()
        if not user:
            user = CustomUser.objects.filter(email=email).first()
            if user:
                user.google_id = google_id
                user.save(update_fields=['google_id'])
            else:
                username = email.split('@')[0]
                base = username
                counter = 1
                while CustomUser.objects.filter(username=username).exists():
                    username = f"{base}{counter}"
                    counter += 1
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    google_id=google_id,
                    role='agent',
                    is_approved=False,
                    email_verified=True,
                )

        if not user.can_access:
            messages.warning(request, tr(
                user.language,
                "Your account is pending admin approval.",
                "حسابك بانتظار موافقة المشرف.",
                "Votre compte est en attente d'approbation administrateur.",
            ))
            return redirect('core:login')

        login(request, user)
        request.session['preferred_language'] = user.language
        _log_security_event(
            'user_login',
            f"User login: {user.username} ({user.role})",
            severity='info',
            source='auth',
            user=user,
            details={
                'role': user.role,
                'auth_method': 'google_oauth',
                'logged_in_at': timezone.now().isoformat(),
            },
        )
        messages.success(request, tr(
            user.language,
            f"Welcome, {user.first_name}!",
            f"مرحبا، {user.first_name}!",
            f"Bienvenue, {user.first_name} !",
        ))
        return redirect('core:dashboard')

    except Exception as e:
        messages.error(request, tr(
            lang,
            "Google login error. Please try again.",
            "خطأ في تسجيل الدخول عبر Google. حاول مرة اخرى.",
            "Erreur de connexion Google. Veuillez reessayer.",
        ))
        return redirect('core:login')


@login_required
def approve_agent(request, user_id):
    """Admin-only: approve a pending agent."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')

    agent = get_object_or_404(CustomUser, id=user_id, role='agent')
    agent.is_approved = True
    agent.save(update_fields=['is_approved'])
    _log_security_event(
        'user_approved',
        f'Agent approved: {agent.username}',
        severity='info',
        source='admin_agents',
        user=request.user,
        details={'agent_id': agent.id, 'agent_email': agent.email},
    )

    send_mail(
        'DroneSec – Account Approved',
        f'Hi {agent.first_name},\n\nYour DroneSec account has been approved! You can now log in.\n\nDroneSec Team',
        settings.DEFAULT_FROM_EMAIL,
        [agent.email],
        fail_silently=True,
    )
    lang = get_lang(request)
    messages.success(request, tr(
        lang,
        f"Agent {agent.get_full_name()} approved.",
        f"تمت الموافقة على الوكيل {agent.get_full_name()}.",
        f"Agent {agent.get_full_name()} approuve.",
    ))
    return redirect(request.META.get('HTTP_REFERER', 'core:dashboard'))


@login_required
def reject_agent(request, user_id):
    """Admin-only: reject/deactivate an agent."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')

    agent = get_object_or_404(CustomUser, id=user_id, role='agent')
    agent.is_approved = False
    agent.is_active = False
    agent.save(update_fields=['is_approved', 'is_active'])
    _log_security_event(
        'user_rejected',
        f'Agent rejected: {agent.username}',
        severity='warning',
        source='admin_agents',
        user=request.user,
        details={'agent_id': agent.id, 'agent_email': agent.email},
    )
    lang = get_lang(request)
    messages.warning(request, tr(
        lang,
        f"Agent {agent.get_full_name()} rejected.",
        f"تم رفض الوكيل {agent.get_full_name()}.",
        f"Agent {agent.get_full_name()} rejete.",
    ))
    return redirect(request.META.get('HTTP_REFERER', 'core:dashboard'))


@login_required
def pending_agents(request):
    """Display pending agent approvals (admin-only)."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')
    
    pending = CustomUser.objects.filter(role='agent', is_approved=False, is_active=True)
    return render(request, 'core/users/pending_agents.html', {'pending_agents': pending})


@login_required
def agents_list(request):
    """Display all agents and admins with activity status (admin-only)."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')
    
    users = CustomUser.objects.filter(role__in=['agent', 'admin'])\
        .exclude(username__iexact='admin')\
        .exclude(id=request.user.id)\
        .order_by('-last_seen')
    
    # Add activity status and last activity info
    lang = get_lang(request)
    for user in users:
        user.activity_status = get_agent_activity_status(user, lang)
    
    # Separate agents and admins for the context
    agents = users.filter(role='agent')
    admins = users.filter(role='admin')
    
    context = {
        'users': users,
        'agents': agents,
        'admins': admins,
        'can_manage_admin_accounts': _is_reserved_main_admin(request.user),
        'total_users': users.count(),
        'total_agents': agents.count(),
        'total_admins': admins.count(),
        'active_agents': agents.filter(is_approved=True, is_active=True).count(),
    }
    return render(request, 'core/users/agents_list.html', context)


@login_required
def elevate_agent_to_admin(request, user_id):
    """Admin-only: elevate an agent to admin role."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')

    agent = get_object_or_404(CustomUser, id=user_id, role='agent')
    agent.role = 'admin'
    agent.save(update_fields=['role'])
    _log_security_event(
        'system_event',
        f'Role changed to admin: {agent.username}',
        severity='warning',
        source='admin_agents',
        user=request.user,
        details={'target_user_id': agent.id},
    )
    
    send_mail(
        'DroneSec – Elevated to Admin',
        f'Hi {agent.first_name},\n\nCongratulations! You have been elevated to Admin role.\n\nDroneSec Team',
        settings.DEFAULT_FROM_EMAIL,
        [agent.email],
        fail_silently=True,
    )
    lang = get_lang(request)
    messages.success(request, tr(
        lang,
        f"Agent {agent.get_full_name()} elevated to Admin.",
        f"تمت ترقية الوكيل {agent.get_full_name()} الى مشرف.",
        f"Agent {agent.get_full_name()} promu administrateur.",
    ))
    return redirect('core:agents_list')


@login_required
def downgrade_admin_to_agent(request, user_id):
    """Admin-only: downgrade an admin to agent role."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')

    if not _is_reserved_main_admin(request.user):
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            "Only the main admin account can manage other admins.",
            "فقط حساب المشرف الرئيسي يمكنه إدارة حسابات المشرفين الآخرين.",
            "Seul le compte administrateur principal peut gerer les autres administrateurs.",
        ))
        return redirect('core:agents_list')

    admin = get_object_or_404(CustomUser, id=user_id, role='admin')
    if admin.id == request.user.id:
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            "You cannot manage your own account from this section.",
            "لا يمكنك إدارة حسابك الشخصي من هذا القسم.",
            "Vous ne pouvez pas gerer votre propre compte depuis cette section.",
        ))
        return redirect('core:agents_list')

    if _is_reserved_main_admin(admin):
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            "The main admin account cannot be managed from this section.",
            "لا يمكن إدارة حساب المشرف الرئيسي من هذا القسم.",
            "Le compte administrateur principal ne peut pas etre gere depuis cette section.",
        ))
        return redirect('core:agents_list')

    admin.role = 'agent'
    admin.save(update_fields=['role'])
    _log_security_event(
        'system_event',
        f'Role changed to agent: {admin.username}',
        severity='warning',
        source='admin_agents',
        user=request.user,
        details={'target_user_id': admin.id},
    )
    
    send_mail(
        'DroneSec – Downgraded to Agent',
        f'Hi {admin.first_name},\n\nYour admin privileges have been revoked. Your role has been changed to Agent.\n\nDroneSec Team',
        settings.DEFAULT_FROM_EMAIL,
        [admin.email],
        fail_silently=True,
    )
    lang = get_lang(request)
    messages.success(request, tr(
        lang,
        f"Admin {admin.get_full_name()} downgraded to Agent.",
        f"تم خفض المشرف {admin.get_full_name()} الى وكيل.",
        f"Admin {admin.get_full_name()} retrograde en agent.",
    ))
    return redirect('core:agents_list')


@login_required
def remove_agent(request, user_id):
    """Admin-only: permanently delete/remove an agent or admin account."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')

    user = get_object_or_404(CustomUser, id=user_id)
    if user.id == request.user.id:
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            "You cannot manage your own account from this section.",
            "لا يمكنك إدارة حسابك الشخصي من هذا القسم.",
            "Vous ne pouvez pas gerer votre propre compte depuis cette section.",
        ))
        return redirect('core:agents_list')

    if _is_reserved_main_admin(user):
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            "The main admin account cannot be managed from this section.",
            "لا يمكن إدارة حساب المشرف الرئيسي من هذا القسم.",
            "Le compte administrateur principal ne peut pas etre gere depuis cette section.",
        ))
        return redirect('core:agents_list')

    # Allow removal of both agents and admins
    if user.role not in ['agent', 'admin']:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Invalid user role.", "دور مستخدم غير صالح.", "Role utilisateur invalide."))
        return redirect('core:agents_list')

    if user.role == 'admin' and not _is_reserved_main_admin(request.user):
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            "Only the main admin account can manage other admins.",
            "فقط حساب المشرف الرئيسي يمكنه إدارة حسابات المشرفين الآخرين.",
            "Seul le compte administrateur principal peut gerer les autres administrateurs.",
        ))
        return redirect('core:agents_list')
    
    user_name = user.get_full_name()
    removed_user_id = user.id
    removed_username = user.username
    
    # Delete the user account permanently
    user.delete()
    _log_security_event(
        'system_event',
        f'User removed: {removed_username}',
        severity='critical',
        source='admin_agents',
        user=request.user,
        details={'removed_user_id': removed_user_id},
    )
    
    lang = get_lang(request)
    messages.warning(request, tr(
        lang,
        f"{user_name} has been permanently removed from the system.",
        f"تمت ازالة {user_name} نهائيا من النظام.",
        f"{user_name} a ete supprime definitivement du systeme.",
    ))
    return redirect('core:agents_list')


@login_required
def inspect_agent(request, user_id):
    """Display detailed information about an agent or admin."""
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Permission denied.", "تم رفض الصلاحية.", "Permission refusee."))
        return redirect('core:dashboard')
    
    user = get_object_or_404(CustomUser, id=user_id)
    if _is_reserved_main_admin(user) and not _is_reserved_main_admin(request.user):
        lang = get_lang(request)
        messages.error(request, tr(
            lang,
            "The main admin account cannot be managed from this section.",
            "لا يمكن إدارة حساب المشرف الرئيسي من هذا القسم.",
            "Le compte administrateur principal ne peut pas etre gere depuis cette section.",
        ))
        return redirect('core:agents_list')

    # Allow inspection of both agents and admins
    if user.role not in ['agent', 'admin']:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Invalid user role.", "دور مستخدم غير صالح.", "Role utilisateur invalide."))
        return redirect('core:agents_list')
    
    user.activity_status = get_agent_activity_status(user, get_lang(request))
    
    # Get user's activities (drones, alerts related to their drones, etc.)
    assigned_drones = Drone.objects.filter(assigned_to=user)
    
    # Get alerts from assigned drones
    alerts_created = Alert.objects.filter(drone__in=assigned_drones).order_by('-created_at')[:10]
    
    context = {
        'agent': user,
        'assigned_drones': assigned_drones,
        'alerts_created': alerts_created,
    }
    return render(request, 'core/users/inspect_agent.html', context)


def get_agent_activity_status(agent, lang='en'):
    """Helper function to determine agent activity status."""
    if not agent.last_seen:
        return {
            'status': 'unknown',
            'label': tr(lang, 'Never logged in', 'لم يسجل الدخول من قبل', 'Jamais connecte'),
            'badge_class': 'status-unknown'
        }
    
    now = timezone.now()
    time_diff = now - agent.last_seen
    
    # Determine status
    if time_diff < timedelta(minutes=5):
        return {
            'status': 'active',
            'label': tr(lang, 'Active', 'نشط', 'Actif'),
            'time_ago': tr(lang, 'Just now', 'الآن', "A l'instant"),
            'badge_class': 'status-active'
        }
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        return {
            'status': 'idle',
            'label': tr(lang, 'Idle', 'خامل', 'Inactif'),
            'time_ago': tr(lang, f'{minutes}m ago', f'منذ {minutes}د', f'il y a {minutes} min'),
            'badge_class': 'status-idle'
        }
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        return {
            'status': 'offline',
            'label': tr(lang, 'Offline', 'غير متصل', 'Hors ligne'),
            'time_ago': tr(lang, f'{hours}h ago', f'منذ {hours}س', f'il y a {hours} h'),
            'badge_class': 'status-offline'
        }
    else:
        days = time_diff.days
        return {
            'status': 'offline',
            'label': tr(lang, 'Offline', 'غير متصل', 'Hors ligne'),
            'time_ago': tr(lang, f'{days}d ago', f'منذ {days}ي', f'il y a {days} j'),
            'badge_class': 'status-offline'
        }


@login_required
def settings_index(request):
    profile_form = ProfileUpdateForm(instance=request.user)
    if request.user.has_usable_password():
        password_form = CustomPasswordChangeForm(request.user)
    else:
        password_form = CustomSetPasswordForm(request.user)
    return render(request, 'core/settings_app/settings.html', {
        'profile_form': profile_form,
        'password_form': password_form,
    })


@login_required
def update_profile(request):
    if request.method == 'POST':
        lang = getattr(request.user, 'language', 'en')
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            user = form.save()
            request.session['preferred_language'] = user.language
            success_msg = {
                'ar': 'تم تحديث الملف الشخصي بنجاح.',
                'fr': 'Le profil a ete mis a jour avec succes.',
                'en': 'Profile updated successfully.',
            }.get(lang, 'Profile updated successfully.')
            messages.success(request, success_msg)
            return redirect('core:settings')
        else:
            # Show form errors instead of generic message
            if form.errors:
                for field, errors in form.errors.items():
                    for error in errors:
                        field_msg = {
                            'ar': f"{field.replace('_', ' ').title()}: {error}",
                            'fr': f"{field.replace('_', ' ').title()} : {error}",
                            'en': f"{field.replace('_', ' ').title()}: {error}",
                        }.get(lang, f"{field.replace('_', ' ').title()}: {error}")
                        messages.error(request, field_msg)
            if request.user.has_usable_password():
                password_form = CustomPasswordChangeForm(request.user)
            else:
                password_form = CustomSetPasswordForm(request.user)
            return render(request, 'core/settings_app/settings.html', {
                'profile_form': form,
                'password_form': password_form,
            })
    return redirect('core:settings')


# ========== CHAT VIEWS ==========
@login_required
def chat_inbox(request, user_id=None):
    if not request.user.can_access:
        return redirect('core:dashboard')

    _touch_last_seen(request.user)

    lang = get_lang(request)
    peers_qs = CustomUser.objects.filter(
        role__in=['agent', 'admin'],
        is_active=True,
    ).exclude(id=request.user.id).order_by('first_name', 'last_name', 'username')

    peers = list(peers_qs)
    peer_ids = [peer.id for peer in peers]
    selected_user = None

    unread_rows = _unread_messages_for_user(request.user).values('sender_id').annotate(total=Count('id'))
    unread_map = {row['sender_id']: row['total'] for row in unread_rows}

    latest_message_id_map = {}
    if peer_ids:
        latest_rows = AgentMessage.objects.filter(
            Q(sender=request.user, recipient_id__in=peer_ids) |
            Q(recipient=request.user, sender_id__in=peer_ids)
        ).filter(
            Q(sender=request.user, is_deleted_for_sender=False) |
            Q(recipient=request.user, is_deleted_for_recipient=False),
            deleted_for_everyone=False,
        ).order_by('-id').values('id', 'sender_id', 'recipient_id')

        for row in latest_rows:
            peer_id = row['recipient_id'] if row['sender_id'] == request.user.id else row['sender_id']
            if peer_id not in latest_message_id_map:
                latest_message_id_map[peer_id] = row['id']
            if len(latest_message_id_map) >= len(peer_ids):
                break

    now = timezone.now()

    for peer in peers:
        peer.chat_unread_count = unread_map.get(peer.id, 0)
        peer.chat_latest_message_id = latest_message_id_map.get(peer.id, 0)
        peer.is_online = bool(peer.last_seen and (now - peer.last_seen) <= timedelta(minutes=5))

    peers_with_activity = [peer for peer in peers if peer.chat_latest_message_id]
    peers_without_activity = [peer for peer in peers if not peer.chat_latest_message_id]
    peers_with_activity.sort(key=lambda peer: peer.chat_latest_message_id, reverse=True)
    peers_without_activity.sort(key=lambda peer: (
        (peer.first_name or '').lower(),
        (peer.last_name or '').lower(),
        (peer.username or '').lower(),
    ))
    peers = peers_with_activity + peers_without_activity

    if user_id is not None:
        selected_user = get_object_or_404(peers_qs, id=user_id)
    elif peers:
        selected_user = peers[0]

    if selected_user and not hasattr(selected_user, 'is_online'):
        selected_user.is_online = bool(
            selected_user.last_seen and (timezone.now() - selected_user.last_seen) <= timedelta(minutes=5)
        )

    initial_messages = []
    if selected_user:
        qs = _conversation_messages_for_user(request.user, selected_user).order_by('id')
        recent_messages = list(qs.order_by('-id')[:80])
        recent_messages.reverse()
        initial_messages = [_serialize_chat_message(msg, request.user) for msg in recent_messages]
        _unread_messages_for_user(request.user).filter(
            sender=selected_user,
        ).update(is_read=True)

    broadcast_departments = []
    if request.user.is_admin:
        broadcast_departments = list(
            CustomUser.objects.filter(is_active=True)
            .exclude(department__isnull=True)
            .exclude(department__exact='')
            .order_by('department')
            .values_list('department', flat=True)
            .distinct()
        )

    return render(request, 'core/users/chat.html', {
        'peers': peers,
        'selected_user': selected_user,
        'initial_messages': initial_messages,
        'broadcast_departments': broadcast_departments,
        'unread_count': _unread_messages_for_user(request.user).count(),
        'lang': lang,
    })


@login_required
def chat_messages_api(request, user_id):
    if not request.user.can_access:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)

    peer = get_object_or_404(
        CustomUser.objects.filter(role__in=['agent', 'admin'], is_active=True).exclude(id=request.user.id),
        id=user_id,
    )

    after_id = request.GET.get('after', '0')
    full_sync = request.GET.get('full', '0') == '1'
    try:
        after_id = int(after_id)
    except ValueError:
        after_id = 0

    messages_qs = _conversation_messages_for_user(request.user, peer).order_by('id')

    if full_sync:
        recent_messages = list(messages_qs.order_by('-id')[:80])
        recent_messages.reverse()
        messages_batch = recent_messages
    else:
        if after_id > 0:
            messages_qs = messages_qs.filter(id__gt=after_id)
        messages_batch = list(messages_qs[:100])

    incoming_ids = [m.id for m in messages_batch if m.sender_id == peer.id and m.recipient_id == request.user.id]
    if incoming_ids:
        _unread_messages_for_user(request.user).filter(id__in=incoming_ids).update(is_read=True)

    return JsonResponse({
        'messages': [_serialize_chat_message(m, request.user) for m in messages_batch],
        'unread_total': _unread_messages_for_user(request.user).count(),
    })


@login_required
def chat_notifications_api(request):
    if not request.user.can_access:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)
    lang = getattr(request.user, 'language', 'en')

    after_id = request.GET.get('after', '0')
    try:
        after_id = int(after_id)
    except ValueError:
        after_id = 0

    incoming_qs = AgentMessage.objects.filter(
        recipient=request.user,
        deleted_for_everyone=False,
        is_deleted_for_recipient=False,
    ).select_related('sender').order_by('-id')
    latest_msg = incoming_qs.first()
    latest_incoming_id = latest_msg.id if latest_msg else 0

    new_messages = []
    if after_id > 0:
        new_qs = AgentMessage.objects.filter(
            recipient=request.user,
            id__gt=after_id,
            deleted_for_everyone=False,
            is_deleted_for_recipient=False,
        ).select_related('sender').order_by('id')[:30]
        new_messages = [
            {
                'id': msg.id,
                'sender_id': msg.sender_id,
                'sender_name': msg.sender.get_full_name() or msg.sender.username,
                'sender_username': msg.sender.username,
                'sender_avatar': _user_avatar_url(msg.sender),
                'message': _message_preview_text(msg, lang),
                'has_voice': bool(msg.voice_message),
                'has_attachment': bool(msg.attachment),
                'attachment_is_image': _attachment_is_image(msg),
                'created_at': timezone.localtime(msg.created_at).strftime('%H:%M'),
                'created_at_full': timezone.localtime(msg.created_at).strftime('%Y-%m-%d %H:%M'),
                'chat_url': f'/chat/{msg.sender_id}/',
            }
            for msg in new_qs
        ]

    unread_qs = _unread_messages_for_user(request.user).select_related('sender').order_by('-id')
    unread_total = unread_qs.count()

    unread_counts = {
        row['sender_id']: row['total']
        for row in unread_qs.values('sender_id').annotate(total=Count('id'))
    }

    latest_unread_by_sender = {}
    for msg in unread_qs[:80]:
        if msg.sender_id not in latest_unread_by_sender:
            latest_unread_by_sender[msg.sender_id] = msg

    unread_preview = [
        {
            'sender_id': msg.sender_id,
            'sender_name': msg.sender.get_full_name() or msg.sender.username,
            'sender_username': msg.sender.username,
            'sender_avatar': _user_avatar_url(msg.sender),
            'count': unread_counts.get(msg.sender_id, 0),
            'message': _message_preview_text(msg, lang),
            'has_voice': bool(msg.voice_message),
            'has_attachment': bool(msg.attachment),
            'attachment_is_image': _attachment_is_image(msg),
            'created_at': timezone.localtime(msg.created_at).strftime('%H:%M'),
            'latest_id': msg.id,
            'chat_url': f'/chat/{msg.sender_id}/',
        }
        for msg in latest_unread_by_sender.values()
    ]
    unread_preview.sort(key=lambda item: item['latest_id'], reverse=True)
    unread_preview = unread_preview[:8]

    return JsonResponse({
        'unread_total': unread_total,
        'unread_preview': unread_preview,
        'new_messages': new_messages,
        'latest_incoming_id': latest_incoming_id,
    })


@login_required
@require_POST
def chat_send_api(request, user_id):
    if not request.user.can_access:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)

    peer = get_object_or_404(
        CustomUser.objects.filter(role__in=['agent', 'admin'], is_active=True).exclude(id=request.user.id),
        id=user_id,
    )
    text = (request.POST.get('message') or '').strip()
    voice_message = request.FILES.get('voice_message')
    attachment = request.FILES.get('attachment')
    voice_duration_seconds = None
    duration_raw = (request.POST.get('voice_duration_seconds') or '').strip()
    reply_to_id = request.POST.get('reply_to_id', '').strip()

    if not text and not voice_message and not attachment:
        return JsonResponse({'error': 'empty'}, status=400)

    if voice_message:
        if voice_message.size > CHAT_VOICE_MAX_BYTES:
            return JsonResponse({'error': 'voice_too_large'}, status=400)
        if not _is_valid_voice_upload(voice_message):
            return JsonResponse({'error': 'voice_invalid_type'}, status=400)

        if duration_raw:
            try:
                voice_duration_seconds = int(duration_raw)
            except ValueError:
                voice_duration_seconds = None
        if voice_duration_seconds is not None:
            voice_duration_seconds = max(1, min(voice_duration_seconds, 3600))

    if attachment and attachment.size > CHAT_ATTACHMENT_MAX_BYTES:
        return JsonResponse({'error': 'attachment_too_large'}, status=400)

    reply_to = None
    if reply_to_id:
        try:
            reply_to_id = int(reply_to_id)
        except ValueError:
            return JsonResponse({'error': 'invalid_reply'}, status=400)

        reply_to = AgentMessage.objects.filter(
            id=reply_to_id,
            deleted_for_everyone=False,
        ).filter(
            Q(sender=request.user, recipient=peer) |
            Q(sender=peer, recipient=request.user)
        ).first()
        if not reply_to:
            return JsonResponse({'error': 'invalid_reply'}, status=400)

    text = text[:1000]
    msg = AgentMessage.objects.create(
        sender=request.user,
        recipient=peer,
        message=text,
        voice_message=voice_message,
        voice_duration_seconds=voice_duration_seconds,
        attachment=attachment,
        reply_to=reply_to,
    )

    return JsonResponse({'message': _serialize_chat_message(msg, request.user)})


@login_required
@require_POST
def chat_broadcast_api(request):
    if not request.user.can_access or not request.user.is_admin:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)

    text = (request.POST.get('message') or '').strip()[:1000]
    if not text:
        return JsonResponse({'error': 'empty'}, status=400)

    audience = (request.POST.get('audience') or 'all').strip().lower()
    department = (request.POST.get('department') or '').strip()[:100]

    recipients_qs = CustomUser.objects.filter(
        role__in=['agent', 'admin'],
        is_active=True,
    ).exclude(id=request.user.id)

    if audience == 'agents':
        recipients_qs = recipients_qs.filter(role='agent')
    elif audience == 'admins':
        recipients_qs = recipients_qs.filter(role='admin')
    elif audience == 'department':
        if not department:
            return JsonResponse({'error': 'department_required'}, status=400)
        recipients_qs = recipients_qs.filter(department__iexact=department)
    elif audience != 'all':
        return JsonResponse({'error': 'invalid_audience'}, status=400)

    recipients = list(
        recipients_qs.values_list('id', flat=True)
    )

    if not recipients:
        return JsonResponse({'status': 'ok', 'sent': 0})

    AgentMessage.objects.bulk_create(
        [
            AgentMessage(
                sender=request.user,
                recipient_id=recipient_id,
                message=text,
                is_broadcast=True,
            )
            for recipient_id in recipients
        ],
        batch_size=200,
    )

    return JsonResponse({
        'status': 'ok',
        'sent': len(recipients),
        'audience': audience,
        'department': department,
    })


@login_required
@require_POST
def chat_react_api(request, message_id):
    if not request.user.can_access:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)

    message = get_object_or_404(
        AgentMessage.objects.filter(deleted_for_everyone=False).filter(
            Q(sender=request.user) | Q(recipient=request.user)
        ),
        id=message_id,
    )

    if not _is_message_visible_to_user(message, request.user):
        return JsonResponse({'error': 'not_found'}, status=404)

    emoji = (request.POST.get('emoji') or '').strip()[:16]
    if emoji:
        AgentMessageReaction.objects.update_or_create(
            message=message,
            user=request.user,
            defaults={'emoji': emoji},
        )
    else:
        AgentMessageReaction.objects.filter(message=message, user=request.user).delete()

    message.refresh_from_db()
    return JsonResponse({'message': _serialize_chat_message(message, request.user)})


@login_required
@require_POST
def chat_delete_message_api(request, message_id):
    if not request.user.can_access:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)

    message = get_object_or_404(
        AgentMessage.objects.filter(deleted_for_everyone=False).filter(
            Q(sender=request.user) | Q(recipient=request.user)
        ),
        id=message_id,
    )

    if not _is_message_visible_to_user(message, request.user):
        return JsonResponse({'error': 'not_found'}, status=404)

    scope = (request.POST.get('scope') or 'self').strip().lower()
    if scope == 'both':
        message.deleted_for_everyone = True
        message.save(update_fields=['deleted_for_everyone'])
        return JsonResponse({'status': 'deleted_for_both'})

    if message.sender_id == request.user.id:
        message.is_deleted_for_sender = True
        message.save(update_fields=['is_deleted_for_sender'])
    else:
        message.is_deleted_for_recipient = True
        message.save(update_fields=['is_deleted_for_recipient'])

    return JsonResponse({'status': 'deleted_for_self'})


@login_required
@require_POST
def chat_delete_conversation_api(request, user_id):
    if not request.user.can_access:
        return JsonResponse({'error': 'forbidden'}, status=403)

    _touch_last_seen(request.user)

    peer = get_object_or_404(
        CustomUser.objects.filter(role__in=['agent', 'admin'], is_active=True).exclude(id=request.user.id),
        id=user_id,
    )

    mode = (request.POST.get('mode') or 'self').strip().lower()
    convo_qs = AgentMessage.objects.filter(
        deleted_for_everyone=False,
    ).filter(
        Q(sender=request.user, recipient=peer)
        | Q(sender=peer, recipient=request.user)
    )

    if mode == 'both':
        deleted_everyone = convo_qs.update(deleted_for_everyone=True)
        return JsonResponse({
            'status': 'ok',
            'mode': 'both',
            'deleted_for_everyone': deleted_everyone,
            'deleted_for_self': 0,
        })

    hidden_sent = convo_qs.filter(sender=request.user).update(is_deleted_for_sender=True)
    hidden_received = convo_qs.filter(sender=peer).update(is_deleted_for_recipient=True)
    return JsonResponse({
        'status': 'ok',
        'mode': 'self',
        'deleted_for_self': hidden_sent + hidden_received,
    })


@login_required
def change_password(request):
    if request.method == 'POST':
        lang = getattr(request.user, 'language', 'en')
        if request.user.has_usable_password():
            form = CustomPasswordChangeForm(request.user, request.POST)
        else:
            form = CustomSetPasswordForm(request.user, request.POST)

        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            success_msg = {
                'ar': 'تم تغيير كلمة المرور بنجاح.',
                'fr': 'Le mot de passe a ete modifie avec succes.',
                'en': 'Password changed successfully.',
            }.get(lang, 'Password changed successfully.')
            messages.success(request, success_msg)
            _log_security_event(
                'system_event',
                'User updated account password from settings.',
                severity='info',
                source='auth',
                user=request.user,
                details={'channel': 'settings', 'had_usable_password': request.user.has_usable_password()},
            )
            return redirect('core:settings')
        else:
            for _, errors in form.errors.items():
                for error in errors:
                    messages.error(request, str(error))

            profile_form = ProfileUpdateForm(instance=request.user)
            return render(request, 'core/settings_app/settings.html', {
                'profile_form': profile_form,
                'password_form': form,
            })
    return redirect('core:settings')


@login_required
@require_POST
def forgot_password_from_settings(request):
    lang = getattr(request.user, 'language', 'en')
    user_email = (getattr(request.user, 'email', '') or '').strip()

    if not user_email:
        messages.error(request, tr(
            lang,
            'No email is linked to your account. Please add an email in profile settings first.',
            'لا يوجد بريد الكتروني مرتبط بحسابك. يرجى اضافة بريد من اعدادات الملف الشخصي اولا.',
            "Aucun e-mail n'est lie a votre compte. Ajoutez d'abord un e-mail dans les parametres du profil.",
        ))
        return redirect('core:settings')

    reset_form = CustomPasswordResetForm({'email': user_email})
    if not reset_form.is_valid():
        messages.error(request, tr(
            lang,
            'Could not send a reset link right now. Please verify your account email and try again.',
            'تعذر ارسال رابط الاستعادة حاليا. يرجى التحقق من بريد الحساب ثم المحاولة مرة اخرى.',
            "Impossible d'envoyer le lien de reinitialisation pour le moment. Verifiez l'e-mail du compte puis reessayez.",
        ))
        return redirect('core:settings')

    try:
        reset_form.save(
            request=request,
            use_https=request.is_secure(),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            email_template_name='core/users/password_reset_email.txt',
            subject_template_name='core/users/password_reset_subject.txt',
        )
        _log_security_event(
            'system_event',
            'Password reset link requested from account settings.',
            severity='info',
            source='auth',
            user=request.user,
            details={'channel': 'settings', 'email': user_email},
        )
        messages.success(request, tr(
            lang,
            'Password reset link sent to your email.',
            'تم ارسال رابط اعادة تعيين كلمة المرور الى بريدك الالكتروني.',
            'Le lien de reinitialisation du mot de passe a ete envoye a votre e-mail.',
        ))
    except Exception:
        messages.error(request, tr(
            lang,
            'Failed to send reset email. Please try again later.',
            'فشل ارسال بريد الاستعادة. يرجى المحاولة لاحقا.',
            "Echec de l'envoi de l'e-mail de reinitialisation. Veuillez reessayer plus tard.",
        ))

    return redirect('core:settings')


# ========== DRONE VIEWS ==========
@login_required
def drone_list(request):
    drones = Drone.objects.all()
    return render(request, 'core/drones/drone_list.html', {'drones': drones})


@login_required
def drone_detail(request, pk):
    drone = get_object_or_404(Drone, pk=pk)
    recent_alerts = Alert.objects.filter(drone=drone).order_by('-created_at')[:10]
    return render(request, 'core/drones/drone_detail.html', {
        'drone': drone,
        'recent_alerts': recent_alerts,
    })


@login_required
def drone_add(request):
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Admin access required.", "يلزم صلاحية المشرف.", "Acces administrateur requis."))
        return redirect('core:drone_list')
    if request.method == 'POST':
        drone = Drone.objects.create(
            name=request.POST.get('name'),
            serial_number=request.POST.get('serial_number'),
            status=request.POST.get('status', 'offline'),
            location_name=request.POST.get('location_name', ''),
            notes=request.POST.get('notes', ''),
        )
        _log_security_event(
            'drone_added',
            f"Drone added: {drone.name}",
            severity='info',
            source='drone_management',
            user=request.user,
            drone=drone,
            details={'serial_number': drone.serial_number, 'status': drone.status},
        )
        if drone.status in ['online', 'patrolling']:
            _log_security_event(
                'drone_deployed',
                f"Drone deployed: {drone.name}",
                severity='warning' if drone.status == 'patrolling' else 'info',
                source='drone_management',
                user=request.user,
                drone=drone,
                details={'status': drone.status, 'location_name': drone.location_name},
            )
        lang = get_lang(request)
        messages.success(request, tr(
            lang,
            f"Drone '{drone.name}' added.",
            f"تمت اضافة الطائرة '{drone.name}'.",
            f"Drone '{drone.name}' ajoute.",
        ))
        return redirect('core:drone_detail', pk=drone.pk)
    return render(request, 'core/drones/drone_form.html', {'action': 'Add'})


@login_required
def drone_edit(request, pk):
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, "Admin access required.", "يلزم صلاحية المشرف.", "Acces administrateur requis."))
        return redirect('core:drone_list')
    drone = get_object_or_404(Drone, pk=pk)
    if request.method == 'POST':
        old_status = drone.status
        drone.name = request.POST.get('name', drone.name)
        drone.status = request.POST.get('status', drone.status)
        drone.location_name = request.POST.get('location_name', drone.location_name)
        drone.notes = request.POST.get('notes', drone.notes)
        drone.save()
        _log_security_event(
            'drone_updated',
            f"Drone updated: {drone.name}",
            severity='info',
            source='drone_management',
            user=request.user,
            drone=drone,
            details={'old_status': old_status, 'new_status': drone.status},
        )
        if old_status != drone.status and drone.status in ['online', 'patrolling']:
            _log_security_event(
                'drone_deployed',
                f"Drone status changed to deployment mode: {drone.name}",
                severity='warning' if drone.status == 'patrolling' else 'info',
                source='drone_management',
                user=request.user,
                drone=drone,
                details={'old_status': old_status, 'new_status': drone.status},
            )
        lang = get_lang(request)
        messages.success(request, tr(
            lang,
            f"Drone '{drone.name}' updated.",
            f"تم تحديث الطائرة '{drone.name}'.",
            f"Drone '{drone.name}' mis a jour.",
        ))
        return redirect('core:drone_detail', pk=drone.pk)
    return render(request, 'core/drones/drone_form.html', {'drone': drone, 'action': 'Edit'})


@login_required
def drone_delete(request, pk):
    if not request.user.is_admin:
        lang = get_lang(request)
        return JsonResponse({'error': tr(lang, 'Permission denied', 'تم رفض الصلاحية', 'Permission refusee')}, status=403)
    drone = get_object_or_404(Drone, pk=pk)
    deleted_name = drone.name
    deleted_id = drone.id
    deleted_serial = drone.serial_number
    drone.delete()
    _log_security_event(
        'drone_removed',
        f"Drone deleted: {deleted_name}",
        severity='warning',
        source='drone_management',
        user=request.user,
        details={'drone_id': deleted_id, 'serial_number': deleted_serial},
    )
    lang = get_lang(request)
    messages.success(request, tr(lang, "Drone deleted.", "تم حذف الطائرة.", "Drone supprime."))
    return redirect('core:drone_list')


@login_required
@require_POST
def drone_control(request, pk):
    lang = get_lang(request)
    if not request.user.is_admin:
        messages.error(request, tr(lang, 'Admin access required.', 'يلزم صلاحية المشرف.', 'Acces administrateur requis.'))
        return redirect('core:drone_list')

    drone = get_object_or_404(Drone, pk=pk)
    action = (request.POST.get('action') or '').strip().lower()
    old_status = drone.status

    if action == 'stop':
        if drone.status == 'offline':
            messages.info(request, tr(
                lang,
                f"Drone '{drone.name}' is already stopped.",
                f"الطائرة '{drone.name}' متوقفة بالفعل.",
                f"Le drone '{drone.name}' est deja arrete.",
            ))
        elif drone.status not in ['online', 'patrolling']:
            messages.warning(request, tr(
                lang,
                f"Drone '{drone.name}' can only be stopped while online or patrolling.",
                f"يمكن ايقاف الطائرة '{drone.name}' فقط عندما تكون متصلة او في دورية.",
                f"Le drone '{drone.name}' ne peut etre arrete que lorsqu'il est en ligne ou en patrouille.",
            ))
        else:
            drone.status = 'offline'
            drone.speed = 0
            drone.altitude = 0
            drone.camera_active = False
            drone.save(update_fields=['status', 'speed', 'altitude', 'camera_active'])

            _log_security_event(
                'system_event',
                f"Emergency drone stop activated: {drone.name}",
                severity='warning',
                source='drone_control',
                user=request.user,
                drone=drone,
                details={'action': 'stop', 'old_status': old_status, 'new_status': drone.status},
            )
            messages.success(request, tr(
                lang,
                f"Drone '{drone.name}' has been stopped.",
                f"تم ايقاف الطائرة '{drone.name}'.",
                f"Le drone '{drone.name}' a ete arrete.",
            ))
    elif action == 'resume':
        if drone.status != 'offline':
            messages.info(request, tr(
                lang,
                f"Drone '{drone.name}' is already allowed to operate.",
                f"الطائرة '{drone.name}' مسموح لها بالعمل بالفعل.",
                f"Le drone '{drone.name}' est deja autorise a fonctionner.",
            ))
        else:
            drone.status = 'online'
            drone.save(update_fields=['status'])

            _log_security_event(
                'drone_deployed',
                f"Drone resumed for operation: {drone.name}",
                severity='info',
                source='drone_control',
                user=request.user,
                drone=drone,
                details={'action': 'resume', 'old_status': old_status, 'new_status': drone.status},
            )
            messages.success(request, tr(
                lang,
                f"Drone '{drone.name}' is now operational.",
                f"الطائرة '{drone.name}' تعمل الآن.",
                f"Le drone '{drone.name}' est maintenant operationnel.",
            ))
    else:
        messages.error(request, tr(
            lang,
            'Invalid control action.',
            'اجراء تحكم غير صالح.',
            'Action de controle invalide.',
        ))

    referrer = request.META.get('HTTP_REFERER')
    if referrer:
        return redirect(referrer)
    return redirect('core:drone_detail', pk=drone.pk)


@login_required
def drone_status_api(request, pk):
    """Simulated live telemetry API for a drone."""
    drone = get_object_or_404(Drone, pk=pk)
    battery_delta = random.randint(-2, 0) if drone.status in ['online', 'patrolling'] else 0
    drone.battery = max(0, min(100, drone.battery + battery_delta))
    drone.latitude += random.uniform(-0.0005, 0.0005)
    drone.longitude += random.uniform(-0.0005, 0.0005)
    drone.altitude = random.uniform(50, 150) if drone.status == 'patrolling' else 0
    drone.speed = random.uniform(20, 60) if drone.status == 'patrolling' else 0
    drone.save(update_fields=['battery', 'latitude', 'longitude', 'altitude', 'speed'])

    return JsonResponse({
        'id': drone.pk,
        'name': drone.name,
        'status': drone.status,
        'battery': drone.battery,
        'latitude': drone.latitude,
        'longitude': drone.longitude,
        'altitude': round(drone.altitude, 1),
        'speed': round(drone.speed, 1),
        'camera_active': drone.camera_active,
        'updated_at': timezone.now().isoformat(),
    })


# ========== ALERT VIEWS ==========
@login_required
def alert_list(request):
    severity = request.GET.get('severity', '')
    alert_type = request.GET.get('type', '')
    resolved = request.GET.get('resolved', '')

    alerts = Alert.objects.all()
    if severity:
        alerts = alerts.filter(severity=severity)
    if alert_type:
        alerts = alerts.filter(alert_type=alert_type)
    if resolved == '0':
        alerts = alerts.filter(is_resolved=False)
    elif resolved == '1':
        alerts = alerts.filter(is_resolved=True)

    lang = get_lang(request)
    severity_map = {
        'en': {'low': 'Low', 'medium': 'Medium', 'high': 'High', 'critical': 'Critical'},
        'ar': {'low': 'منخفض', 'medium': 'متوسط', 'high': 'عال', 'critical': 'حرج'},
        'fr': {'low': 'Faible', 'medium': 'Moyenne', 'high': 'Elevee', 'critical': 'Critique'},
    }
    type_map = {
        'en': {
            'intrusion': 'Intrusion Detected', 'face': 'Face Recognized', 'object': 'Object Detected',
            'motion': 'Motion Detected', 'battery': 'Low Battery', 'connection': 'Connection Lost',
            'geofence': 'Geofence Breach', 'system': 'System Alert',
        },
        'ar': {
            'intrusion': 'تم كشف التسلل', 'face': 'تم التعرف على الوجه', 'object': 'تم كشف جسم',
            'motion': 'تم كشف حركة', 'battery': 'بطارية منخفضة', 'connection': 'انقطاع الاتصال',
            'geofence': 'خرق النطاق الجغرافي', 'system': 'تنبيه نظام',
        },
        'fr': {
            'intrusion': 'Intrusion detectee', 'face': 'Visage reconnu', 'object': 'Objet detecte',
            'motion': 'Mouvement detecte', 'battery': 'Batterie faible', 'connection': 'Connexion perdue',
            'geofence': 'Violation de geofence', 'system': 'Alerte systeme',
        },
    }
    s_map = severity_map.get(lang, severity_map['en'])
    t_map = type_map.get(lang, type_map['en'])
    severity_choices = [(code, s_map.get(code, label)) for code, label in Alert.SEVERITY_CHOICES]
    type_choices = [(code, t_map.get(code, label)) for code, label in Alert.TYPE_CHOICES]

    return render(request, 'core/alerts/alert_list.html', {
        'alerts': alerts[:50],
        'severity_choices': severity_choices,
        'type_choices': type_choices,
    })


@login_required
def alert_detail(request, pk):
    alert = get_object_or_404(Alert, pk=pk)
    if not alert.is_read:
        alert.is_read = True
        alert.save(update_fields=['is_read'])
    return render(request, 'core/alerts/alert_detail.html', {'alert': alert})


@login_required
def resolve_alert(request, pk):
    alert = get_object_or_404(Alert, pk=pk)
    alert.is_resolved = True
    alert.resolved_by = request.user
    alert.save(update_fields=['is_resolved', 'resolved_by'])
    _log_security_event(
        'alert_resolved',
        f"Alert resolved: #{alert.id} {alert.title}",
        severity='info',
        source='alerts',
        user=request.user,
        drone=alert.drone,
        alert=alert,
        details={'severity': alert.severity, 'alert_type': alert.alert_type},
    )
    lang = get_lang(request)
    messages.success(request, tr(lang, "Alert resolved.", "تم حل التنبيه.", "Alerte resolue."))
    return redirect(request.META.get('HTTP_REFERER', 'core:alert_list'))


@login_required
@require_POST
def alert_delete(request, pk):
    lang = get_lang(request)
    if not request.user.is_admin:
        messages.error(request, tr(
            lang,
            'Admin access required.',
            'يلزم صلاحية المشرف.',
            'Acces administrateur requis.',
        ))
        return redirect(request.META.get('HTTP_REFERER', 'core:alert_list'))

    alert = get_object_or_404(Alert, pk=pk)
    deleted_id = alert.id
    deleted_title = alert.title
    deleted_severity = alert.severity
    deleted_type = alert.alert_type
    deleted_drone = alert.drone
    alert.delete()

    _log_security_event(
        'system_event',
        f"Alert deleted: #{deleted_id} {deleted_title}",
        severity='warning',
        source='alerts',
        user=request.user,
        drone=deleted_drone,
        details={
            'action': 'alert_delete',
            'alert_id': deleted_id,
            'title': deleted_title,
            'severity': deleted_severity,
            'alert_type': deleted_type,
        },
    )

    messages.success(request, tr(
        lang,
        'Alert deleted.',
        'تم حذف التنبيه.',
        'Alerte supprimee.',
    ))
    return redirect(request.META.get('HTTP_REFERER', 'core:alert_list'))


@login_required
@require_POST
def alert_delete_all(request):
    lang = get_lang(request)
    if not request.user.is_admin:
        messages.error(request, tr(
            lang,
            'Admin access required.',
            'يلزم صلاحية المشرف.',
            'Acces administrateur requis.',
        ))
        return redirect(request.META.get('HTTP_REFERER', 'core:alert_list'))

    deleted_count, _ = Alert.objects.all().delete()
    if deleted_count <= 0:
        messages.info(request, tr(
            lang,
            'No alerts to delete.',
            'لا توجد تنبيهات للحذف.',
            'Aucune alerte a supprimer.',
        ))
        return redirect(request.META.get('HTTP_REFERER', 'core:alert_list'))

    _log_security_event(
        'system_event',
        f"All alerts deleted by admin: {deleted_count} records",
        severity='critical',
        source='alerts',
        user=request.user,
        details={
            'action': 'alert_delete_all',
            'deleted_count': deleted_count,
        },
    )

    messages.success(request, tr(
        lang,
        f'All alerts deleted ({deleted_count}).',
        f'تم حذف جميع التنبيهات ({deleted_count}).',
        f'Toutes les alertes ont ete supprimees ({deleted_count}).',
    ))
    return redirect(request.META.get('HTTP_REFERER', 'core:alert_list'))


@login_required
def live_alerts_api(request):
    """Return recent unread alerts as JSON for live polling."""
    alerts = Alert.objects.filter(is_read=False, is_resolved=False).order_by('-created_at')[:5]
    lang = get_lang(request)
    type_map = {
        'en': {
            'intrusion': 'Intrusion Detected', 'face': 'Face Recognized', 'object': 'Object Detected',
            'motion': 'Motion Detected', 'battery': 'Low Battery', 'connection': 'Connection Lost',
            'geofence': 'Geofence Breach', 'system': 'System Alert',
        },
        'ar': {
            'intrusion': 'تم كشف التسلل', 'face': 'تم التعرف على الوجه', 'object': 'تم كشف جسم',
            'motion': 'تم كشف حركة', 'battery': 'بطارية منخفضة', 'connection': 'انقطاع الاتصال',
            'geofence': 'خرق النطاق الجغرافي', 'system': 'تنبيه نظام',
        },
        'fr': {
            'intrusion': 'Intrusion detectee', 'face': 'Visage reconnu', 'object': 'Objet detecte',
            'motion': 'Mouvement detecte', 'battery': 'Batterie faible', 'connection': 'Connexion perdue',
            'geofence': 'Violation de geofence', 'system': 'Alerte systeme',
        },
    }
    t_map = type_map.get(lang, type_map['en'])
    data = [{
        'id': a.pk,
        'title': a.title,
        'severity': a.severity,
        'severity_color': a.severity_color,
        'alert_type': t_map.get(a.alert_type, a.get_alert_type_display()),
        'drone': a.drone.name if a.drone else tr(lang, 'System', 'النظام', 'Systeme'),
        'created_at': a.created_at.strftime('%H:%M:%S'),
    } for a in alerts]
    return JsonResponse({'alerts': data, 'count': len(data)})


@login_required
def simulate_alert(request):
    """Dev helper: create a random simulated alert."""
    drones = Drone.objects.filter(status__in=['online', 'patrolling'])
    drone = random.choice(list(drones)) if drones else None
    severity = random.choice(['low', 'medium', 'high', 'critical'])
    alert_type = random.choice([c[0] for c in Alert.TYPE_CHOICES])
    lang = get_lang(request)
    titles = {
        'en': {
            'intrusion': 'Unauthorized person detected',
            'face': 'Unknown face identified',
            'object': 'Suspicious object detected',
            'motion': 'Unexpected motion in zone',
            'battery': 'Drone battery critical',
            'connection': 'Drone signal lost',
            'geofence': 'Drone left designated zone',
            'system': 'System anomaly detected',
        },
        'ar': {
            'intrusion': 'تم كشف شخص غير مصرح',
            'face': 'تم تحديد وجه غير معروف',
            'object': 'تم كشف جسم مشبوه',
            'motion': 'حركة غير متوقعة في المنطقة',
            'battery': 'بطارية الطائرة حرجة',
            'connection': 'فقدان اشارة الطائرة',
            'geofence': 'خرجت الطائرة من النطاق المحدد',
            'system': 'تم كشف خلل في النظام',
        },
        'fr': {
            'intrusion': 'Personne non autorisee detectee',
            'face': 'Visage inconnu identifie',
            'object': 'Objet suspect detecte',
            'motion': 'Mouvement inattendu dans la zone',
            'battery': 'Batterie du drone critique',
            'connection': 'Signal du drone perdu',
            'geofence': 'Le drone a quitte la zone definie',
            'system': 'Anomalie systeme detectee',
        },
    }
    t_titles = titles.get(lang, titles['en'])
    alert = Alert.objects.create(
        title=t_titles.get(alert_type, tr(lang, 'Alert', 'تنبيه', 'Alerte')),
        description=tr(
            lang,
            f"Auto-generated simulation alert at {timezone.now().strftime('%H:%M:%S')}.",
            f"تنبيه محاكاة تم توليده تلقائيا عند {timezone.now().strftime('%H:%M:%S')}.",
            f"Alerte de simulation generee automatiquement a {timezone.now().strftime('%H:%M:%S')}.",
        ),
        severity=severity,
        alert_type=alert_type,
        drone=drone,
    )
    _log_security_event(
        'alert_created',
        f"Simulated alert created: #{alert.id} {alert.title}",
        severity='critical' if severity == 'critical' else ('warning' if severity in ['high', 'medium'] else 'info'),
        source='alert_simulation',
        user=request.user,
        drone=drone,
        alert=alert,
        details={'severity': severity, 'alert_type': alert_type},
    )
    return JsonResponse({'status': 'created', 'alert_id': alert.pk, 'title': alert.title})


# ========== MONITORING VIEWS ==========
class _FallbackLiveStreamControl:
    state = 'active'
    admin_note = ''


def _get_livestream_control():
    try:
        control, _ = LiveStreamControl.objects.get_or_create(singleton_key='global')
        return control
    except (OperationalError, ProgrammingError):
        # Keep monitoring pages usable before migration is applied.
        return _FallbackLiveStreamControl()


@login_required
def live_stream(request, drone_id=None):
    control = _get_livestream_control()
    lang = get_lang(request)

    drones = Drone.objects.filter(status__in=['online', 'patrolling'])
    selected = get_object_or_404(Drone, pk=drone_id) if drone_id else drones.first()
    state = control.state

    blocked_for_user = (state in ['suspended', 'shutdown']) and (not request.user.is_admin)
    blocked_title = ''
    blocked_message = ''
    if blocked_for_user:
        if state == 'suspended':
            blocked_title = tr(
                lang,
                'Live stream is temporarily suspended',
                'البث المباشر متوقف مؤقتا',
                'Le flux en direct est temporairement suspendu',
            )
            blocked_message = tr(
                lang,
                'An admin has temporarily suspended live monitoring. Please try again later.',
                'قام المشرف بتعليق المراقبة المباشرة مؤقتا. يرجى المحاولة لاحقا.',
                'Un administrateur a temporairement suspendu la surveillance en direct. Veuillez reessayer plus tard.',
            )
        else:
            blocked_title = tr(
                lang,
                'Live stream is shut down',
                'البث المباشر متوقف بالكامل',
                'Le flux en direct est arrete',
            )
            blocked_message = tr(
                lang,
                'An admin has shut down live monitoring. Access is currently unavailable.',
                'قام المشرف بايقاف المراقبة المباشرة بالكامل. الوصول غير متاح حاليا.',
                'Un administrateur a arrete la surveillance en direct. L acces est actuellement indisponible.',
            )

    return render(request, 'core/monitoring/live_stream.html', {
        'drones': drones,
        'selected': selected,
        'livestream_state': state,
        'livestream_admin_note': control.admin_note,
        'livestream_blocked_for_user': blocked_for_user,
        'livestream_blocked_title': blocked_title,
        'livestream_blocked_message': blocked_message,
    })


@login_required
@require_POST
def live_stream_control(request):
    lang = get_lang(request)
    if not request.user.is_admin:
        messages.error(request, tr(lang, 'Admin access required.', 'يلزم صلاحية المشرف.', 'Acces administrateur requis.'))
        return redirect('core:live_stream')

    control = _get_livestream_control()
    if not isinstance(control, LiveStreamControl):
        messages.error(request, tr(
            lang,
            'Live stream controls are not ready yet. Apply database migrations first.',
            'عناصر تحكم البث المباشر غير جاهزة بعد. يرجى تطبيق ترحيلات قاعدة البيانات اولا.',
            'Les controles du flux en direct ne sont pas encore prets. Appliquez d abord les migrations de base de donnees.',
        ))
        return redirect('core:live_stream')

    old_state = control.state
    action = (request.POST.get('action') or '').strip().lower()
    admin_note = (request.POST.get('admin_note') or '').strip()[:255]

    action_to_state = {
        'resume': 'active',
        'suspend': 'suspended',
        'shutdown': 'shutdown',
    }
    target_state = action_to_state.get(action)
    if not target_state:
        messages.error(request, tr(
            lang,
            'Invalid livestream control action.',
            'اجراء تحكم غير صالح للبث المباشر.',
            'Action de controle du flux en direct invalide.',
        ))
        return redirect('core:live_stream')

    if old_state == target_state and (not admin_note or admin_note == (control.admin_note or '')):
        messages.info(request, tr(
            lang,
            'Live stream state is already set to this mode.',
            'حالة البث المباشر مضبوطة مسبقا على هذا الوضع.',
            'L etat du flux en direct est deja defini sur ce mode.',
        ))
        return redirect('core:live_stream')

    control.state = target_state
    control.admin_note = admin_note
    control.updated_by = request.user
    control.save(update_fields=['state', 'admin_note', 'updated_by', 'updated_at'])

    severity = 'warning' if target_state in ['suspended', 'shutdown'] else 'info'
    _log_security_event(
        'system_event',
        f'Live stream control changed from {old_state} to {target_state}.',
        severity=severity,
        source='live_stream_control',
        user=request.user,
        details={
            'old_state': old_state,
            'new_state': target_state,
            'admin_note': admin_note,
        },
    )

    if target_state == 'suspended':
        messages.success(request, tr(
            lang,
            'Live stream has been temporarily suspended.',
            'تم تعليق البث المباشر مؤقتا.',
            'Le flux en direct a ete suspendu temporairement.',
        ))
    elif target_state == 'shutdown':
        messages.success(request, tr(
            lang,
            'Live stream has been shut down.',
            'تم ايقاف البث المباشر بالكامل.',
            'Le flux en direct a ete arrete.',
        ))
    else:
        messages.success(request, tr(
            lang,
            'Live stream has been resumed.',
            'تمت اعادة تشغيل البث المباشر.',
            'Le flux en direct a ete repris.',
        ))

    return redirect('core:live_stream')


@login_required
def monitoring_logs(request):
    logs = MonitoringLog.objects.select_related('drone').all()[:100]
    return render(request, 'core/monitoring/logs.html', {'logs': logs})


@login_required
def stream_feed_api(request, drone_id):
    """Simulate live telemetry data for the monitoring feed."""
    control = _get_livestream_control()
    if control.state in ['suspended', 'shutdown'] and not request.user.is_admin:
        lang = get_lang(request)
        if control.state == 'suspended':
            msg = tr(
                lang,
                'Live stream is temporarily suspended by an admin.',
                'البث المباشر معلق مؤقتا من طرف المشرف.',
                'Le flux en direct est temporairement suspendu par un administrateur.',
            )
        else:
            msg = tr(
                lang,
                'Live stream has been shut down by an admin.',
                'تم ايقاف البث المباشر من طرف المشرف.',
                'Le flux en direct a ete arrete par un administrateur.',
            )
        return JsonResponse({
            'error': 'livestream_unavailable',
            'state': control.state,
            'message': msg,
        }, status=423)

    drone = get_object_or_404(Drone, pk=drone_id)
    detections = [
        {'type': 'person', 'confidence': random.randint(85, 99), 'x': random.randint(10, 80), 'y': random.randint(10, 80)},
        {'type': 'vehicle', 'confidence': random.randint(70, 95), 'x': random.randint(10, 80), 'y': random.randint(10, 80)},
    ] if random.random() > 0.4 else []

    if detections:
        session_key = f'last_detection_log_{drone.id}'
        now_epoch = int(time.time())
        last_epoch = int(request.session.get(session_key) or 0)
        if now_epoch - last_epoch >= 45:
            max_conf = max(det.get('confidence') or 0 for det in detections)
            _log_security_event(
                'detection_event',
                f'Detection event from {drone.name}',
                severity='warning' if max_conf >= 95 else 'info',
                source='live_monitoring',
                user=request.user,
                drone=drone,
                details={'detections_count': len(detections), 'max_confidence': max_conf},
            )
            request.session[session_key] = now_epoch

    return JsonResponse({
        'drone_id': drone.pk,
        'status': drone.status,
        'battery': drone.battery,
        'detections': detections,
        'fps': round(random.uniform(24, 30), 1),
        'signal': random.randint(70, 100),
        'timestamp': int(time.time()),
    })


@login_required
def security_system_logs(request):
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, 'Admin access required.', 'يلزم صلاحية المشرف.', 'Acces administrateur requis.'))
        return redirect('core:dashboard')

    lang = get_lang(request)
    event_type = (request.GET.get('event') or '').strip()
    severity = (request.GET.get('severity') or '').strip()
    source = (request.GET.get('source') or '').strip()
    since = (request.GET.get('since') or '').strip()
    query = (request.GET.get('q') or '').strip()

    logs_qs = SecuritySystemLog.objects.select_related('user', 'drone', 'alert').all()

    if event_type:
        logs_qs = logs_qs.filter(event_type=event_type)
    if severity:
        logs_qs = logs_qs.filter(severity=severity)
    if source:
        logs_qs = logs_qs.filter(source__icontains=source)
    if since == '24h':
        logs_qs = logs_qs.filter(created_at__gte=timezone.now() - timedelta(hours=24))
    elif since == '7d':
        logs_qs = logs_qs.filter(created_at__gte=timezone.now() - timedelta(days=7))
    elif since == '30d':
        logs_qs = logs_qs.filter(created_at__gte=timezone.now() - timedelta(days=30))

    if query:
        logs_qs = logs_qs.filter(
            Q(message__icontains=query)
            | Q(user__username__icontains=query)
            | Q(drone__name__icontains=query)
            | Q(alert__title__icontains=query)
            | Q(source__icontains=query)
        )

    logs = logs_qs[:400]
    context = {
        'logs': logs,
        'event_choices': SecuritySystemLog.EVENT_CHOICES,
        'severity_choices': SecuritySystemLog.SEVERITY_CHOICES,
        'total_logs': logs_qs.count(),
        'critical_count': logs_qs.filter(severity='critical').count(),
        'warning_count': logs_qs.filter(severity='warning').count(),
        'info_count': logs_qs.filter(severity='info').count(),
        'page_title_override': tr(lang, 'Security System Logs', 'سجلات النظام الامني', 'Journaux systeme de securite'),
    }
    return render(request, 'core/admin/security_logs.html', context)


@login_required
@require_POST
def security_system_logs_delete(request):
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, 'Admin access required.', 'يلزم صلاحية المشرف.', 'Acces administrateur requis.'))
        return redirect('core:dashboard')

    lang = get_lang(request)
    scope = (request.POST.get('delete_scope') or '').strip()
    now = timezone.now()

    if scope == 'selected':
        raw_ids = request.POST.getlist('log_ids')
        ids = [int(value) for value in raw_ids if str(value).isdigit()]
        if not ids:
            messages.warning(request, tr(
                lang,
                'Select at least one log to delete.',
                'حدد سجلا واحدا على الاقل للحذف.',
                'Selectionnez au moins un journal a supprimer.',
            ))
            return redirect('core:security_system_logs')

        deleted_count, _ = SecuritySystemLog.objects.filter(id__in=ids).delete()
        messages.success(request, tr(
            lang,
            f'Deleted {deleted_count} selected logs.',
            f'تم حذف {deleted_count} سجلات محددة.',
            f'{deleted_count} journaux selectionnes supprimes.',
        ))
        return redirect('core:security_system_logs')

    if scope == 'all':
        deleted_count, _ = SecuritySystemLog.objects.all().delete()
        messages.success(request, tr(
            lang,
            f'Deleted all logs ({deleted_count}).',
            f'تم حذف كل السجلات ({deleted_count}).',
            f'Tous les journaux ont ete supprimes ({deleted_count}).',
        ))
        return redirect('core:security_system_logs')

    if scope == '24h':
        qs = SecuritySystemLog.objects.filter(created_at__gte=now - timedelta(hours=24))
        deleted_count, _ = qs.delete()
        messages.success(request, tr(
            lang,
            f'Deleted logs from the last 24 hours ({deleted_count}).',
            f'تم حذف سجلات آخر 24 ساعة ({deleted_count}).',
            f'Journaux des dernieres 24h supprimes ({deleted_count}).',
        ))
        return redirect('core:security_system_logs')

    if scope == '7d':
        qs = SecuritySystemLog.objects.filter(created_at__gte=now - timedelta(days=7))
        deleted_count, _ = qs.delete()
        messages.success(request, tr(
            lang,
            f'Deleted logs from the last 7 days ({deleted_count}).',
            f'تم حذف سجلات آخر 7 ايام ({deleted_count}).',
            f'Journaux des 7 derniers jours supprimes ({deleted_count}).',
        ))
        return redirect('core:security_system_logs')

    if scope == '30d':
        qs = SecuritySystemLog.objects.filter(created_at__gte=now - timedelta(days=30))
        deleted_count, _ = qs.delete()
        messages.success(request, tr(
            lang,
            f'Deleted logs from the last 30 days ({deleted_count}).',
            f'تم حذف سجلات آخر 30 يوما ({deleted_count}).',
            f'Journaux des 30 derniers jours supprimes ({deleted_count}).',
        ))
        return redirect('core:security_system_logs')

    messages.warning(request, tr(
        lang,
        'Unknown delete action.',
        'اجراء الحذف غير معروف.',
        'Action de suppression inconnue.',
    ))
    return redirect('core:security_system_logs')


@login_required
def stream_recordings_admin(request):
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, 'Admin access required.', 'يلزم صلاحية المشرف.', 'Acces administrateur requis.'))
        return redirect('core:dashboard')

    lang = get_lang(request)
    if request.method == 'POST':
        upload_form = StreamRecordingUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            recording = upload_form.save(commit=False)
            recording.uploaded_by = request.user
            recording.file_size_bytes = int(getattr(recording.recording_file, 'size', 0) or 0)
            recording.save()
            _log_security_event(
                'recording_uploaded',
                f'Recording uploaded: {recording.title}',
                severity='info',
                source='recordings_admin',
                user=request.user,
                drone=recording.drone,
                details={'recording_id': recording.id, 'size_bytes': recording.file_size_bytes},
            )
            messages.success(request, tr(
                lang,
                'Recording uploaded successfully.',
                'تم رفع التسجيل بنجاح.',
                'Enregistrement televerse avec succes.',
            ))
            return redirect('core:stream_recordings_admin')
    else:
        upload_form = StreamRecordingUploadForm()

    query = (request.GET.get('q') or '').strip()
    drone_id = (request.GET.get('drone') or '').strip()

    recordings_qs = StreamRecording.objects.select_related('drone', 'uploaded_by').all()
    if query:
        recordings_qs = recordings_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(drone__name__icontains=query)
            | Q(uploaded_by__username__icontains=query)
        )
    if drone_id:
        recordings_qs = recordings_qs.filter(drone_id=drone_id)

    context = {
        'upload_form': upload_form,
        'recordings': recordings_qs[:300],
        'drones': Drone.objects.all()[:100],
        'total_recordings': recordings_qs.count(),
    }
    return render(request, 'core/admin/recordings.html', context)


@login_required
def stream_recording_download(request, recording_id):
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, 'Admin access required.', 'يلزم صلاحية المشرف.', 'Acces administrateur requis.'))
        return redirect('core:dashboard')

    recording = get_object_or_404(StreamRecording, id=recording_id)
    if not recording.recording_file:
        raise FileNotFoundError('Recording file was not found.')

    _log_security_event(
        'recording_downloaded',
        f'Recording downloaded: {recording.title}',
        severity='info',
        source='recordings_admin',
        user=request.user,
        drone=recording.drone,
        details={'recording_id': recording.id},
    )
    filename = os.path.basename(recording.recording_file.name)
    return FileResponse(recording.recording_file.open('rb'), as_attachment=True, filename=filename)


@login_required
@require_POST
def stream_recording_delete(request, recording_id):
    if not request.user.is_admin:
        lang = get_lang(request)
        messages.error(request, tr(lang, 'Admin access required.', 'يلزم صلاحية المشرف.', 'Acces administrateur requis.'))
        return redirect('core:dashboard')

    recording = get_object_or_404(StreamRecording, id=recording_id)
    recording_title = recording.title
    recording_drone = recording.drone
    recording_id_value = recording.id

    if recording.recording_file:
        recording.recording_file.delete(save=False)
    recording.delete()

    _log_security_event(
        'recording_deleted',
        f'Recording deleted: {recording_title}',
        severity='warning',
        source='recordings_admin',
        user=request.user,
        drone=recording_drone,
        details={'recording_id': recording_id_value},
    )

    lang = get_lang(request)
    messages.success(request, tr(
        lang,
        'Recording deleted successfully.',
        'تم حذف التسجيل بنجاح.',
        'Enregistrement supprime avec succes.',
    ))
    return redirect('core:stream_recordings_admin')


# ========== REPORTS VIEWS ==========
def _count_alerts_for_day(day):
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(day, dt_time.min), tz)
    end_dt = start_dt + timedelta(days=1)
    return Alert.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt).count()


@login_required
def reports_index(request):
    today = timezone.localdate()
    days = []
    alert_counts = []
    for i in range(7, 0, -1):
        day = today - timedelta(days=i)
        count = _count_alerts_for_day(day)
        days.append(day.strftime('%a'))
        alert_counts.append(count)

    severity_data = {
        'low': Alert.objects.filter(severity='low').count(),
        'medium': Alert.objects.filter(severity='medium').count(),
        'high': Alert.objects.filter(severity='high').count(),
        'critical': Alert.objects.filter(severity='critical').count(),
    }

    drone_stats = {d.name: Alert.objects.filter(drone=d).count()
                   for d in Drone.objects.all()}

    reports = Report.objects.all()
    return render(request, 'core/reports/reports.html', {
        'days': days, 'alert_counts': alert_counts,
        'severity_data': severity_data,
        'drone_stats': drone_stats,
        'reports': reports,
        'total_alerts': Alert.objects.count(),
        'resolved': Alert.objects.filter(is_resolved=True).count(),
        'active_drones': Drone.objects.filter(status__in=['online', 'patrolling']).count(),
    })


@login_required
def chart_data_api(request):
    """JSON data for Chart.js."""
    today = timezone.localdate()
    days, counts = [], []
    for i in range(7, 0, -1):
        day = today - timedelta(days=i)
        days.append(day.strftime('%a %d'))
        counts.append(_count_alerts_for_day(day))

    return JsonResponse({
        'labels': days,
        'alerts_per_day': counts,
        'severity': {
            'labels': ['Low', 'Medium', 'High', 'Critical'],
            'data': [
                Alert.objects.filter(severity='low').count(),
                Alert.objects.filter(severity='medium').count(),
                Alert.objects.filter(severity='high').count(),
                Alert.objects.filter(severity='critical').count(),
            ],
        },
    })
