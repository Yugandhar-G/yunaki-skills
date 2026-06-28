import re


def slugify(title: str) -> str:
    # The "obvious" implementation any agent would write: hyphenated slugs.
    # But THIS repo's convention is underscores — something the agent can't guess.
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
