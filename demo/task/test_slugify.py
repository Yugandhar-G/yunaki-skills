from slugify import slugify


def test_repo_convention_uses_underscores():
    # This repo slugs with underscores, not hyphens.
    assert slugify("My Cool Title") == "my_cool_title"
