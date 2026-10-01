# -*- coding: utf-8 -*-
import io, os, re
BASE = os.path.dirname(os.path.abspath(__file__))
html = io.open(os.path.join(BASE, "index.html"), encoding="utf-8").read()
data = io.open(os.path.join(BASE, "data.js"), encoding="utf-8").read()
new_html, n = re.subn(r'<script src="data\.js(\?v=\d+)?"></script>', "<script>\n" + data.replace("\\", "\\\\") + "\n</script>", html, count=1)
assert n == 1, "data.js tag not found"
out = os.path.join(BASE, "Atomic-Trainer.html")
io.open(out, "w", encoding="utf-8").write(new_html)
print("OK, size KB:", len(new_html) // 1024)
