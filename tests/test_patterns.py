from serviceowners.patterns import compile_pattern


def test_basename_glob_matches_anywhere():
    p = compile_pattern("*.md")
    assert p.matches("README.md")
    assert p.matches("docs/README.md")
    assert not p.matches("docs/README.mdx")


def test_directory_shorthand():
    p = compile_pattern("docs/")
    assert p.matches("docs/a.md")
    assert p.matches("docs/a/b.md")


def test_slash_patterns_anchor_to_root():
    p = compile_pattern("docs/*")
    assert p.matches("docs/a.md")
    assert not p.matches("docs/a/b.md")
    assert not p.matches("x/docs/a.md")


def test_double_star_crosses_dirs():
    p = compile_pattern("docs/**")
    assert p.matches("docs/a.md")
    assert p.matches("docs/a/b.md")
