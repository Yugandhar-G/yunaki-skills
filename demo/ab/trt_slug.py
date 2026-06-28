import re


def slugify(title: str) -> str:
    """Convert a human title into a URL slug (lowercase, words separated)."""
    # Convert to lowercase
    slug = title.lower()
    # Replace any sequence of non-alphanumeric characters with a single underscore
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    # Strip leading and trailing underscores
    slug = slug.strip('_')
    return slug
