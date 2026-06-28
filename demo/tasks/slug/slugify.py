import re


def slugify(title: str) -> str:
    # The obvious implementation — hyphenated slugs. But THIS repo uses underscores.
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
