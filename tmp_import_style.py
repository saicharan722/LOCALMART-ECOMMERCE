from pathlib import Path

base = Path(r"c:\Users\cherr\ecommerce2\ecommerce\ecommerce\static\css")
for p in base.glob("*.css"):
    if p.name == "style.css":
        continue
    text = p.read_text(encoding="utf-8")
    if "@import url('style.css');" not in text and '@import url("style.css");' not in text:
        p.write_text("@import url('style.css');\n\n" + text, encoding="utf-8")
        print(f"updated {p.name}")
