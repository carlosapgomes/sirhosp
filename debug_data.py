"""Verify chart data in rendered template."""
import django, os, json, re
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.test import Client
from django.contrib.auth.models import User

admin, _ = User.objects.get_or_create(username="admin", defaults={"is_superuser": True})
c = Client()
c.force_login(admin)
resp = c.get("/painel/altas/", HTTP_HOST="localhost")
content = resp.content.decode()

m = re.search(
    r'<script[^>]*id="chart-data"[^>]*>(.*?)</script>', content, re.DOTALL
)
if m:
    data = json.loads(m.group(1).strip())
    print(f"labels: {data['labels']}")
    print(f"counts: {data['counts']}")
else:
    print("chart-data NOT FOUND")
    # Check if login page
    if "login" in content.lower()[:500]:
        print("Got login page instead!")
    print(f"Content length: {len(content)}")
