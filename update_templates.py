import re

# Read the views file
with open('c:\\Users\\zegna\\Desktop\\dronesec\\core\\views.py', 'r') as f:
    content = f.read()

# Replace template paths - keeping the structure consistent
replacements = {
    r"render\(request, 'core/dashboard\.html'": "render(request, 'core/dashboard/index.html'",
    r"render\(request, 'core/login\.html'": "render(request, 'core/users/login.html'",
    r"render\(request, 'core/register\.html'": "render(request, 'core/users/register.html'",
    r"render\(request, 'core/pending\.html'": "render(request, 'core/dashboard/pending.html'",
    r"render\(request, 'core/pending_agents\.html'": "render(request, 'core/users/pending_agents.html'",
    r"render\(request, 'core/settings\.html'": "render(request, 'core/settings_app/settings.html'",
    r"render\(request, 'core/drone_list\.html'": "render(request, 'core/drones/drone_list.html'",
    r"render\(request, 'core/drone_detail\.html'": "render(request, 'core/drones/drone_detail.html'",
    r"render\(request, 'core/drone_form\.html'": "render(request, 'core/drones/drone_form.html'",
    r"render\(request, 'core/alert_list\.html'": "render(request, 'core/alerts/alert_list.html'",
    r"render\(request, 'core/alert_detail\.html'": "render(request, 'core/alerts/alert_detail.html'",
    r"render\(request, 'core/live_stream\.html'": "render(request, 'core/monitoring/live_stream.html'",
    r"render\(request, 'core/logs\.html'": "render(request, 'core/monitoring/logs.html'",
    r"render\(request, 'core/reports\.html'": "render(request, 'core/reports/reports.html'",
}

for pattern, replacement in replacements.items():
    content = re.sub(pattern, replacement, content)

with open('c:\\Users\\zegna\\Desktop\\dronesec\\core\\views.py', 'w') as f:
    f.write(content)

print("✅ Updated all template paths in views.py")
