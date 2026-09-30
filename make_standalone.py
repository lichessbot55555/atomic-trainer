# -*- coding: utf-8 -*-
import os
BASE = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(BASE, "index.html"), encoding="utf-8").read()
data = open(os.path.join(BASE, "data.js"), encoding="utf-8").read()
marker = '<script src="data.js"></script>'
assert marker in html, "marker not found"
standalone = html.replace(marker, "<script>\n" + data + "\n</script>")
out = os.path.join(BASE, "Atomic-Trainer.html")
open(out, "w", encoding="utf-8").write(standalone)
print("OK, size KB:", len(standalone) // 1024)
