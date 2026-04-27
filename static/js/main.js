/* ═══════════════════════════════════════════════════════════════
   DroneSec — Main JavaScript
   Live Alerts · Notifications · UI Interactions
═══════════════════════════════════════════════════════════════ */

// ── Toast auto-dismiss ────────────────────────────────────────
document.querySelectorAll('.toast[data-auto-dismiss]').forEach(t => {
  const dismissAfter = Number(t.getAttribute('data-auto-dismiss-ms') || 4000);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transform = 'translateX(30px)';
    t.style.transition = 'all 0.4s ease';
    setTimeout(() => t.remove(), 400);
  }, dismissAfter);
});

// ── Notification panel toggle ─────────────────────────────────
const notifBtn = document.getElementById('notif-btn');
const notifPanel = document.getElementById('notif-panel');
const msgBtn = document.getElementById('msg-btn');
const msgPanel = document.getElementById('msg-panel');

if (notifBtn && notifPanel) {
  notifBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    notifPanel.classList.toggle('open');
    if (msgPanel) msgPanel.classList.remove('open');
  });
}

if (msgBtn && msgPanel) {
  msgBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    msgPanel.classList.toggle('open');
    if (notifPanel) notifPanel.classList.remove('open');
    // Ask permission only after user interaction
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {});
    }
  });
}

document.addEventListener('click', (e) => {
  if (notifPanel && notifBtn && !notifPanel.contains(e.target) && !e.target.closest('#notif-btn')) {
    notifPanel.classList.remove('open');
  }
  if (msgPanel && msgBtn && !msgPanel.contains(e.target) && !e.target.closest('#msg-btn')) {
    msgPanel.classList.remove('open');
  }
});

// ── Live alerts polling ───────────────────────────────────────
let lastAlertId = 0;
let knownAlertIds = new Set();
let alertsInitialized = false;
const recentAlertPopupAt = new Map();

function shouldPopupAlert(alert) {
  const now = Date.now();
  const fingerprint = [alert.alert_type, alert.title].join('|').toLowerCase();
  const isUnknownFace = /unknown face|visage inconnu|وجه غير معروف/i.test(alert.title || '');
  const cooldownMs = isUnknownFace ? 5 * 60 * 1000 : 60 * 1000;
  const lastShownAt = recentAlertPopupAt.get(fingerprint) || 0;

  if (now - lastShownAt < cooldownMs) {
    return false;
  }

  recentAlertPopupAt.set(fingerprint, now);
  return true;
}
const pageLang = (document.documentElement.getAttribute('lang') || 'en').toLowerCase();

const uiText = {
  en: {
    noNewAlerts: 'No new alerts',
    noNewMessages: 'No new messages',
    openChat: 'Open Chat',
    messageFrom: 'New message from',
    unreadSuffix: 'unread',
    alertSimulated: 'Alert simulated: ',
    couldNotSimulate: 'Could not simulate alert',
  },
  ar: {
    noNewAlerts: 'لا توجد تنبيهات جديدة',
    noNewMessages: 'لا توجد رسائل جديدة',
    openChat: 'فتح المحادثة',
    messageFrom: 'رسالة جديدة من',
    unreadSuffix: 'غير مقروءة',
    alertSimulated: 'تمت محاكاة تنبيه: ',
    couldNotSimulate: 'تعذرت محاكاة التنبيه',
  },
  fr: {
    noNewAlerts: 'Aucune nouvelle alerte',
    noNewMessages: 'Aucun nouveau message',
    openChat: 'Ouvrir la messagerie',
    messageFrom: 'Nouveau message de',
    unreadSuffix: 'non lus',
    alertSimulated: 'Alerte simulee : ',
    couldNotSimulate: "Impossible de simuler l'alerte",
  },
};

const t = uiText[pageLang] || uiText.en;

function escapeHtml(text) {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function initialsOf(name) {
  const words = (name || '').trim().split(/\s+/).filter(Boolean);
  const first = words[0]?.[0] || '?';
  const second = words[1]?.[0] || '';
  return (first + second).toUpperCase();
}

function avatarMarkup(avatarUrl, name) {
  if (avatarUrl) {
    return `<img src="${escapeHtml(avatarUrl)}" alt="avatar" class="msg-item-avatar" />`;
  }
  return `<span class="msg-item-avatar-fallback">${escapeHtml(initialsOf(name))}</span>`;
}

let chatNotifyLastIncomingId = 0;
let chatNotifyInitialized = false;
const seenIncomingMessageIds = new Set();

function renderMessageCenter(previewRows, unreadTotal) {
  const dot = document.getElementById('msg-dot');
  const count = document.getElementById('msg-count');
  const list = document.getElementById('msg-list');

  if (dot) dot.style.display = unreadTotal > 0 ? 'block' : 'none';
  if (count) count.textContent = String(unreadTotal || 0);

  if (!list) return;

  if (!previewRows || previewRows.length === 0) {
    list.innerHTML = `<p class="notif-empty">${t.noNewMessages}</p>`;
    return;
  }

  list.innerHTML = previewRows.map(item => {
    const unreadLabel = item.count > 1 ? `${item.count} ${t.unreadSuffix}` : `1 ${t.unreadSuffix}`;
    return `
      <a href="${escapeHtml(item.chat_url)}" class="msg-item">
        ${avatarMarkup(item.sender_avatar, item.sender_name)}
        <div class="msg-item-body">
          <div class="msg-item-head">
            <span class="msg-item-name">${escapeHtml(item.sender_name)}</span>
            <span class="msg-item-time">${escapeHtml(item.created_at)}</span>
          </div>
          <div class="msg-item-text">${escapeHtml(item.message)}</div>
          <span class="msg-item-count">${escapeHtml(unreadLabel)}</span>
        </div>
      </a>
    `;
  }).join('');
}

function playMessagePing() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;

    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.exponentialRampToValueAtTime(0.08, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);

    const osc1 = ctx.createOscillator();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(760, now);
    osc1.connect(gain);
    osc1.start(now);
    osc1.stop(now + 0.11);

    const osc2 = ctx.createOscillator();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(920, now + 0.12);
    osc2.connect(gain);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.24);

    setTimeout(() => ctx.close().catch(() => {}), 420);
  } catch (_) {
    // Ignore sound failures on locked or unsupported audio contexts.
  }
}

function showMessagePopup(item) {
  let stack = document.getElementById('message-popup-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'message-popup-stack';
    document.body.appendChild(stack);
  }

  const popup = document.createElement('div');
  popup.className = 'message-popup';
  popup.innerHTML = `
    <div class="message-popup-head">
      <i class="fa fa-message"></i>
      <span>${escapeHtml(t.messageFrom)}</span>
      <button type="button" aria-label="close"><i class="fa fa-xmark"></i></button>
    </div>
    <div class="message-popup-body">
      ${avatarMarkup(item.sender_avatar, item.sender_name)}
      <div class="message-popup-content">
        <div class="message-popup-name">${escapeHtml(item.sender_name)}</div>
        <div class="message-popup-text">${escapeHtml(item.message)}</div>
      </div>
    </div>
  `;

  popup.addEventListener('click', (e) => {
    if (e.target.closest('button')) {
      popup.remove();
      return;
    }
    window.location = item.chat_url;
  });

  stack.prepend(popup);
  while (stack.children.length > 4) {
    stack.lastElementChild?.remove();
  }

  setTimeout(() => {
    if (popup.parentNode) {
      popup.style.opacity = '0';
      popup.style.transform = 'translateX(30px)';
      popup.style.transition = 'all 0.35s ease';
      setTimeout(() => popup.remove(), 360);
    }
  }, 9000);
}

function showBrowserMessage(item) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  if (!document.hidden) return;
  try {
    const n = new Notification(item.sender_name, {
      body: item.message,
      icon: item.sender_avatar || undefined,
      tag: `chat-${item.sender_id}`,
    });
    n.onclick = () => {
      window.focus();
      window.location = item.chat_url;
    };
    setTimeout(() => n.close(), 6500);
  } catch (_) {}
}

function fetchChatNotifications() {
  const api = '/chat/api/notifications/?after=' + Number(chatNotifyLastIncomingId || 0);
  fetch(api)
    .then(r => r.json())
    .then(data => {
      const unreadTotal = Number(data.unread_total || 0);
      renderMessageCenter(data.unread_preview || [], unreadTotal);

      window.dispatchEvent(new CustomEvent('chat-notifications-updated', {
        detail: data,
      }));

      const latestId = Number(data.latest_incoming_id || 0);
      if (!chatNotifyInitialized) {
        chatNotifyInitialized = true;
        chatNotifyLastIncomingId = latestId;
        return;
      }

      const incoming = Array.isArray(data.new_messages) ? data.new_messages : [];
      if (incoming.length) {
        let played = false;
        incoming.forEach(item => {
          const msgId = Number(item.id || 0);
          if (!msgId || seenIncomingMessageIds.has(msgId)) return;
          seenIncomingMessageIds.add(msgId);
          showMessagePopup(item);
          showBrowserMessage(item);
          if (!played) {
            playMessagePing();
            played = true;
          }
        });
      }

      chatNotifyLastIncomingId = Math.max(chatNotifyLastIncomingId, latestId);
    })
    .catch(() => {});
}

function fetchLiveAlerts() {
  fetch('/alerts/api/live/')
    .then(r => r.json())
    .then(data => {
      const dot = document.getElementById('notif-dot');
      const count = document.getElementById('notif-count');
      const list = document.getElementById('notif-list');

      if (data.alerts && data.alerts.length > 0) {
        if (dot) dot.style.display = 'block';
        if (count) count.textContent = data.count;

        // Build notification list
        if (list) {
          list.innerHTML = data.alerts.map(a => `
            <div class="notif-item" onclick="window.location='/alerts/${a.id}/'">
              <span class="notif-sev-dot" style="background:${a.severity_color}"></span>
              <div>
                <div class="notif-item-title">${a.title}</div>
                <div class="notif-item-meta">${a.alert_type} · ${a.drone} · ${a.created_at}</div>
              </div>
            </div>
          `).join('');
        }

        const freshAlerts = [];
        data.alerts.forEach(a => {
          if (!knownAlertIds.has(a.id)) {
            freshAlerts.push(a);
          }
          knownAlertIds.add(a.id);
          lastAlertId = Math.max(lastAlertId, Number(a.id) || 0);
        });

        // Avoid replaying old unread alerts when the page first loads.
        if (alertsInitialized) {
          freshAlerts.forEach(a => {
            if (shouldPopupAlert(a)) {
              showAlertPopup(a);
            }
          });
        } else {
          alertsInitialized = true;
        }

      } else {
        if (dot) dot.style.display = 'none';
        if (count) count.textContent = '0';
        if (list) list.innerHTML = `<p class="notif-empty">${t.noNewAlerts}</p>`;
      }
    })
    .catch(() => {}); // Silently fail
}

// Poll every 12 seconds
setInterval(fetchLiveAlerts, 12000);
fetchLiveAlerts();

// Poll message notifications every 3 seconds
setInterval(fetchChatNotifications, 3000);
fetchChatNotifications();

// ── Alert popup ───────────────────────────────────────────────
function showAlertPopup(alert) {
  // Remove any existing popup
  document.querySelectorAll('.alert-popup').forEach(p => p.remove());

  const severityColors = {
    critical: '#ef4444',
    high:     '#f97316',
    medium:   '#f59e0b',
    low:      '#22c55e',
  };

  const popup = document.createElement('div');
  popup.className = 'alert-popup glass';
  popup.style.borderColor = (severityColors[alert.severity] || '#38bdf8') + '60';
  popup.innerHTML = `
    <div class="alert-popup-header" style="background:${severityColors[alert.severity]}20;color:${severityColors[alert.severity]}">
      <i class="fa fa-triangle-exclamation"></i>
      <span>${alert.severity.toUpperCase()} ALERT</span>
      <button class="alert-popup-close" onclick="this.closest('.alert-popup').remove()">
        <i class="fa fa-xmark"></i>
      </button>
    </div>
    <div class="alert-popup-body">
      <strong>${alert.title}</strong>
      <div class="alert-popup-meta">
        <i class="fa fa-clock"></i> ${alert.created_at}
      </div>
    </div>
  `;

  popup.style.cursor = 'pointer';
  popup.addEventListener('click', (e) => {
    if (!e.target.closest('.alert-popup-close')) {
      window.location = `/alerts/${alert.id}/`;
    }
  });

  document.body.appendChild(popup);

  // Auto-dismiss after 8s
  setTimeout(() => {
    if (popup.parentNode) {
      popup.style.opacity = '0';
      popup.style.transform = 'translateX(30px)';
      popup.style.transition = 'all 0.4s ease';
      setTimeout(() => popup.remove(), 400);
    }
  }, 8000);
}

// ── Simulate alert (dev helper) ───────────────────────────────
function simulateAlert() {
  fetch('/alerts/api/simulate/')
    .then(r => r.json())
    .then(data => {
      if (data.status === 'created') {
        showToast('⚡ ' + t.alertSimulated + data.title, 'warning');
        fetchLiveAlerts();
      }
    })
    .catch(() => showToast(t.couldNotSimulate, 'error'));
}

// ── Toast helper ──────────────────────────────────────────────
function showToast(message, type = 'info') {
  const iconMap = { success: 'fa-check-circle', error: 'fa-exclamation-circle', warning: 'fa-triangle-exclamation', info: 'fa-info-circle' };
  const container = document.getElementById('toast-container') || (() => {
    const c = document.createElement('div');
    c.id = 'toast-container';
    document.body.appendChild(c);
    return c;
  })();

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <i class="fa ${iconMap[type] || 'fa-info-circle'}"></i>
    <span>${message}</span>
    <button class="toast-close" onclick="this.parentElement.remove()"><i class="fa fa-xmark"></i></button>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(30px)';
    toast.style.transition = 'all 0.4s ease';
    setTimeout(() => toast.remove(), 400);
  }, 4500);
}

// ── Drone telemetry mini-animation ───────────────────────────
document.querySelectorAll('.drone-mini-card').forEach(card => {
  card.addEventListener('mouseenter', () => {
    card.style.boxShadow = '0 4px 20px rgba(56,189,248,0.15)';
  });
  card.addEventListener('mouseleave', () => {
    card.style.boxShadow = '';
  });
});

// ── Tooltip system ────────────────────────────────────────────
document.querySelectorAll('[data-tooltip]').forEach(el => {
  el.style.position = 'relative';
  el.addEventListener('mouseenter', function() {
    if (!document.getElementById('sidebar').classList.contains('collapsed')) return;
    const tip = document.createElement('div');
    tip.className = 'ds-tooltip';
    tip.textContent = this.dataset.tooltip;
    tip.style.cssText = `
      position:fixed; background:#0a1628; color:#e2e8f0; padding:5px 10px;
      border-radius:6px; font-size:12px; white-space:nowrap; z-index:9999;
      border:1px solid rgba(56,189,248,0.2); pointer-events:none;
    `;
    document.body.appendChild(tip);
    const rect = this.getBoundingClientRect();
    tip.style.left = (rect.right + 8) + 'px';
    tip.style.top = (rect.top + rect.height / 2 - tip.offsetHeight / 2) + 'px';
    this._tooltip = tip;
  });
  el.addEventListener('mouseleave', function() {
    if (this._tooltip) { this._tooltip.remove(); this._tooltip = null; }
  });
});

// ── Confirm delete links ──────────────────────────────────────
document.querySelectorAll('a[data-confirm]').forEach(a => {
  a.addEventListener('click', e => {
    if (!confirm(a.dataset.confirm)) e.preventDefault();
  });
});

// ── Mobile sidebar toggle ─────────────────────────────────────
if (window.innerWidth <= 768) {
  document.querySelector('#sidebar-toggle')?.addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('mobile-open');
  });
}

// ── AI assistant robot widget ───────────────────────────────
(function initAiAssistantWidget() {
  const widget = document.getElementById('ai-bot-widget');
  if (!widget) return;

  const toggle = document.getElementById('ai-bot-toggle');
  const panel = document.getElementById('ai-bot-panel');
  const closeBtn = document.getElementById('ai-bot-close');
  const form = document.getElementById('ai-bot-form');
  const input = document.getElementById('ai-bot-input');
  const messages = document.getElementById('ai-bot-messages');
  const apiUrl = widget.getAttribute('data-api-url') || '/assistant/api/chat/';
  const head = widget.querySelector('.ai-bot-head');
  const eyes = Array.from(widget.querySelectorAll('.ai-bot-eye'));
  const pupils = Array.from(widget.querySelectorAll('.ai-bot-pupil'));
  const juggleBall = widget.querySelector('.ai-bot-juggle-ball');
  const defaultGreetingText = ((messages.querySelector('.ai-bot-msg-bot') || {}).textContent || '').trim();
  const history = [];
  let panelOpen = false;
  const pageBoredAfterMs = 30000;
  const boredNoMouseMs = 12000;
  const ballFallMs = 1800;
  const sleepyDuringFallDelayMs = 950;
  const sleepyToAsleepMs = 3800;
  const nearRobotRadiusPx = 150;
  const mouseLingerAfterNearMs = 4000;
  let pageBoredTimer = null;
  let boredNoMouseTimer = null;
  let ballFallTimer = null;
  let sleepyDuringFallTimer = null;
  let sleepyToAsleepTimer = null;
  let stayedOnPageLongEnough = false;
  let lastMouseX = null;
  let lastMouseY = null;
  let mouseBallOverrideUntil = 0;
  if (!toggle || !panel || !form || !input || !messages || !head || eyes.length !== pupils.length) return;
  let sleepState = 'awake';
  const pupilOrbitPx = 4.4;

  if (!toggle || !panel || !form || !input || !messages || !head) return;

  function getCookie(name) {
    const cookieValue = document.cookie
      .split(';')
      .map(part => part.trim())
      .find(part => part.startsWith(name + '='));
    return cookieValue ? decodeURIComponent(cookieValue.split('=').slice(1).join('=')) : '';
  }

  function safeHtml(text) {
    return (text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function addMessage(role, text, extraClass) {
    const node = document.createElement('div');
    const cls = role === 'user' ? 'ai-bot-msg-user' : 'ai-bot-msg-bot';
    node.className = 'ai-bot-msg ' + cls + (extraClass ? (' ' + extraClass) : '');
    node.innerHTML = safeHtml(text || '').replace(/\n/g, '<br>');
    messages.appendChild(node);
    messages.scrollTop = messages.scrollHeight;
    return node;
  }

  function addThinkingBubble() {
    const node = document.createElement('div');
    node.className = 'ai-bot-msg ai-bot-msg-bot ai-bot-msg-typing';
    node.innerHTML = '<span class="ai-bot-thinking"><span></span><span></span><span></span></span>';
    messages.appendChild(node);
    messages.scrollTop = messages.scrollHeight;
    return node;
  }

  function pushHistory(role, content) {
    const text = (content || '').trim();
    if (!text) return;
    history.push({ role, content: text });
    if (history.length > 16) {
      history.splice(0, history.length - 16);
    }
  }

  function setHistoryFromServer(serverHistory) {
    history.length = 0;
    messages.innerHTML = '';

    const thread = Array.isArray(serverHistory) ? serverHistory : [];
    thread.forEach(item => {
      if (!item || typeof item !== 'object') return;
      const role = String(item.role || '').toLowerCase();
      const content = String(item.content || '').trim();
      if (!content) return;

      const mappedRole = role === 'user' ? 'user' : 'assistant';
      history.push({ role: mappedRole, content });
      addMessage(mappedRole === 'user' ? 'user' : 'bot', content);
    });

    if (!history.length && defaultGreetingText) {
      addMessage('bot', defaultGreetingText);
    }
  }

  function loadHistoryFromServer() {
    fetch(apiUrl, {
      method: 'GET',
      credentials: 'same-origin',
      headers: {
        'Accept': 'application/json',
      },
    })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('history_load_failed'))))
      .then(data => {
        setHistoryFromServer(data?.history);
      })
      .catch(() => {
        // Keep default greeting when history fetch fails.
      });
  }

  function syncPanelState(isOpen) {
    panelOpen = !!isOpen;
    panel.hidden = !panelOpen;
    panel.setAttribute('aria-hidden', panelOpen ? 'false' : 'true');
  }

  function openPanel() {
    if (panelOpen) return;
    syncPanelState(true);
    setTimeout(() => input.focus(), 10);
  }

  function closePanel() {
    if (!panelOpen) return;
    syncPanelState(false);
  }

  function togglePanel() {
    if (panelOpen) closePanel(); else openPanel();
  }

  function clamp(v, min, max) {
    return Math.min(max, Math.max(min, v));
  }

  function setSleepState(nextState) {
    if (sleepState === nextState) return;
    sleepState = nextState;
    widget.classList.toggle('ai-bot-sleepy', sleepState === 'sleepy' || sleepState === 'asleep');
    widget.classList.toggle('ai-bot-asleep', sleepState === 'asleep');
    if (sleepState !== 'awake') {
      pupils.forEach(p => {
        p.style.transform = 'translate(-50%, -50%)';
      });
    }
  }

  function resetFaceTracking() {
    head.style.transform = '';
    pupils.forEach(p => {
      p.style.transform = 'translate(-50%, -50%)';
    });
  }

  function isJugglingActive() {
    return widget.classList.contains('ai-bot-bored') && !widget.classList.contains('ai-bot-ball-falling');
  }

  function isMouseNearRobot() {
    if (lastMouseX === null || lastMouseY === null) return false;
    return isPointNearRobot(lastMouseX, lastMouseY);
  }

  function isPointNearRobot(x, y) {
    if (x === null || y === null) return false;
    const rect = widget.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    return Math.hypot(x - cx, y - cy) <= nearRobotRadiusPx;
  }

  function trackTarget(x, y) {
    eyes.forEach((eye, i) => {
      const rect = eye.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = x - cx;
      const dy = y - cy;
      const angle = Math.atan2(dy, dx);
      const distance = Math.min(pupilOrbitPx, Math.hypot(dx, dy));
      const px = Math.cos(angle) * distance;
      const py = Math.sin(angle) * distance;
      pupils[i].style.transform = `translate(calc(-50% + ${px}px), calc(-50% + ${py}px))`;
    });
  }

  function updateEyeTracking() {
    if (sleepState !== 'awake') {
      requestAnimationFrame(updateEyeTracking);
      return;
    }

    const keepMouseFocus = (lastMouseX !== null && lastMouseY !== null) && (isMouseNearRobot() || Date.now() < mouseBallOverrideUntil);

    if (isJugglingActive() && juggleBall && !keepMouseFocus) {
      const ballRect = juggleBall.getBoundingClientRect();
      const bx = ballRect.left + ballRect.width / 2;
      const by = ballRect.top + ballRect.height / 2;
      trackTarget(bx, by);
    } else if (lastMouseX !== null && lastMouseY !== null) {
      trackTarget(lastMouseX, lastMouseY);
    }

    requestAnimationFrame(updateEyeTracking);
  }

  function clearBoredTransitionTimers() {
    if (boredNoMouseTimer) clearTimeout(boredNoMouseTimer);
    if (ballFallTimer) clearTimeout(ballFallTimer);
    if (sleepyDuringFallTimer) clearTimeout(sleepyDuringFallTimer);
    if (sleepyToAsleepTimer) clearTimeout(sleepyToAsleepTimer);
  }

  function scheduleBoredNoMouseTimer() {
    if (!widget.classList.contains('ai-bot-bored')) return;
    if (boredNoMouseTimer) clearTimeout(boredNoMouseTimer);
    boredNoMouseTimer = setTimeout(() => {
      widget.classList.add('ai-bot-ball-falling');
      sleepyDuringFallTimer = setTimeout(() => {
        if (widget.classList.contains('ai-bot-ball-falling')) {
          setSleepState('sleepy');
        }
      }, sleepyDuringFallDelayMs);
      ballFallTimer = setTimeout(() => {
        widget.classList.remove('ai-bot-ball-falling');
        widget.classList.remove('ai-bot-bored');
        if (sleepState === 'awake') {
          setSleepState('sleepy');
        }
        sleepyToAsleepTimer = setTimeout(() => {
          setSleepState('asleep');
        }, sleepyToAsleepMs);
      }, ballFallMs);
    }, boredNoMouseMs);
  }

  function enterBoredMode() {
    if (sleepState !== 'awake') return;
    widget.classList.add('ai-bot-bored');
    widget.classList.remove('ai-bot-ball-falling');
    scheduleBoredNoMouseTimer();
  }

  function schedulePageBoredTimer() {
    if (pageBoredTimer) clearTimeout(pageBoredTimer);
    pageBoredTimer = setTimeout(() => {
      stayedOnPageLongEnough = true;
      enterBoredMode();
    }, pageBoredAfterMs);
  }

  function onMouseActivity() {
    clearBoredTransitionTimers();
    widget.classList.remove('ai-bot-ball-falling');
    if (sleepState !== 'awake') {
      setSleepState('awake');
    }
    if (stayedOnPageLongEnough) {
      enterBoredMode();
    }
    if (widget.classList.contains('ai-bot-bored')) {
      scheduleBoredNoMouseTimer();
    }
  }

  document.addEventListener('mousemove', (e) => {
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
    if (isJugglingActive() && isPointNearRobot(e.clientX, e.clientY)) {
      mouseBallOverrideUntil = Date.now() + mouseLingerAfterNearMs;
    }
    onMouseActivity();
  });

  document.addEventListener('touchmove', onMouseActivity, { passive: true });

  document.addEventListener('mouseleave', () => {
    lastMouseX = null;
    lastMouseY = null;
    mouseBallOverrideUntil = 0;
    resetFaceTracking();
  });

  // Force closed on initial load to avoid any stale/restored DOM state.
  syncPanelState(false);
  schedulePageBoredTimer();
  updateEyeTracking();
  loadHistoryFromServer();

  toggle.addEventListener('click', (e) => {
    e.preventDefault();
    togglePanel();
  });

  closeBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    closePanel();
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = (input.value || '').trim();
    if (!text) return;

    addMessage('user', text);
    pushHistory('user', text);
    input.value = '';
    const typing = addThinkingBubble();
    const startedAt = Date.now();

    fetch(apiUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: JSON.stringify({
        message: text,
        history,
        path: window.location.pathname,
      }),
    })
      .then(r => r.json())
      .then(data => {
        const minWait = Math.max(200, Number(data?.think_ms) || 850);
        const remaining = Math.max(0, minWait - (Date.now() - startedAt));
        setTimeout(() => {
          typing.remove();
          if (Array.isArray(data?.history)) {
            setHistoryFromServer(data.history);
            return;
          }

          if (data && data.reply) {
            addMessage('bot', data.reply);
            pushHistory('assistant', data.reply);
          } else {
            const fallback = 'I could not answer that right now.';
            addMessage('bot', fallback);
            pushHistory('assistant', fallback);
          }
        }, remaining);
      })
      .catch(() => {
        const remaining = Math.max(0, 700 - (Date.now() - startedAt));
        setTimeout(() => {
          typing.remove();
          const fallback = 'Connection issue. Please try again.';
          addMessage('bot', fallback);
          pushHistory('assistant', fallback);
        }, remaining);
      });
  });
})();
