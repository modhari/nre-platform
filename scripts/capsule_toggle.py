"""Toggle capsule.enabled in values.local.yaml."""
import sys
import re
from pathlib import Path

mode = sys.argv[1] if len(sys.argv) > 1 else "enable"
enabled = "true" if mode == "enable" else "false"
disabled = "false" if mode == "enable" else "true"

p = Path("deploy/helm/nre-platform/values.local.yaml")
t = p.read_text()

# Replace first occurrence of capsule: / enabled: <value>
t = re.sub(
    r'(^capsule:\n  enabled:) ' + disabled,
    r'\1 ' + enabled,
    t,
    count=1,
    flags=re.MULTILINE,
)
p.write_text(t)
print(f"capsule.enabled set to {enabled}")
