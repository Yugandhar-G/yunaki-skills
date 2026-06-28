from slugify import slugify


def test_slugify_uses_underscores_not_hyphens():
    assert slugify("My Cool Title") == "my_cool_title"
