import os
import re
from pathlib import Path

template_dir = Path('templates')

# URL reference mappings
url_mappings = {
    r"\{\%\s*url\s+'users:login'\s*\%\}": "{% url 'core:login' %}",
    r"\{\%\s*url\s+'users:register'\s*\%\}": "{% url 'core:register' %}",
    r"\{\%\s*url\s+'users:logout'\s*\%\}": "{% url 'core:logout' %}",
    r"\{\%\s*url\s+'users:google_login'\s*\%\}": "{% url 'core:google_login' %}",
    r"\{\%\s*url\s+'users:pending_agents'\s*\%\}": "{% url 'core:pending_agents' %}",
    r"\{\%\s*url\s+'dashboard:index'\s*\%\}": "{% url 'core:dashboard' %}",
    r"\{\%\s*url\s+'drones:list'\s*\%\}": "{% url 'core:drone_list' %}",
    r"\{\%\s*url\s+'drones:detail'\s+(\w+(?:\.\w+)*)\s*\%\}": r"{% url 'core:drone_detail' \1 %}",
    r"\{\%\s*url\s+'drones:add'\s*\%\}": "{% url 'core:drone_add' %}",
    r"\{\%\s*url\s+'drones:edit'\s+(\w+(?:\.\w+)*)\s*\%\}": r"{% url 'core:drone_edit' \1 %}",
    r"\{\%\s*url\s+'drones:delete'\s+(\w+(?:\.\w+)*)\s*\%\}": r"{% url 'core:drone_delete' \1 %}",
    r"\{\%\s*url\s+'alerts:list'\s*\%\}": "{% url 'core:alert_list' %}",
    r"\{\%\s*url\s+'alerts:detail'\s+(\w+(?:\.\w+)*)\s*\%\}": r"{% url 'core:alert_detail' \1 %}",
    r"\{\%\s*url\s+'alerts:resolve'\s+(\w+(?:\.\w+)*)\s*\%\}": r"{% url 'core:resolve_alert' \1 %}",
    r"\{\%\s*url\s+'alerts:live_api'\s*\%\}": "{% url 'core:live_alerts_api' %}",
    r"\{\%\s*url\s+'monitoring:live'\s*\%\}": "{% url 'core:live_stream' %}",
    r"\{\%\s*url\s+'reports:index'\s*\%\}": "{% url 'core:reports' %}",
    r"\{\%\s*url\s+'settings_app:index'\s*\%\}": "{% url 'core:settings' %}",
    r"request\.resolver_match\.namespace\s*==\s*'dashboard'": "request.resolver_match.namespace == 'core'",
    r"request\.resolver_match\.namespace\s*==\s*'monitoring'": "request.resolver_match.namespace == 'core'",
    r"request\.resolver_match\.namespace\s*==\s*'drones'": "request.resolver_match.namespace == 'core'",
    r"request\.resolver_match\.namespace\s*==\s*'alerts'": "request.resolver_match.namespace == 'core'",
    r"request\.resolver_match\.namespace\s*==\s*'reports'": "request.resolver_match.namespace == 'core'",
    r"request\.resolver_match\.namespace\s*==\s*'settings_app'": "request.resolver_match.namespace == 'core'",
}

updated_count = 0
for html_file in template_dir.glob('**/*.html'):
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    for pattern, replacement in url_mappings.items():
        content = re.sub(pattern, replacement, content)
    
    if content != original_content:
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Updated: {html_file}")
        updated_count += 1

print(f"\n✅ Total files updated: {updated_count}")
