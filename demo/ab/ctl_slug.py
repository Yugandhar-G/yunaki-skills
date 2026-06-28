import re


def slugify(title: str) -> str:
    """Convert a human title into a URL slug (lowercase, words separated)."""
    # Convert to lowercase
    slug = title.lower()

    # Replace spaces and underscores with hyphens
    slug = re.sub(r'[\s_]+', '-', slug)

    # Remove all non-alphanumeric characters except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)

    # Collapse consecutive hyphens into a single hyphen
    slug = re.sub(r'-+', '-', slug)

    # Strip leading and trailing hyphens
    slug = slug.strip('-')

    return slug
