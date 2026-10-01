from perflens.source_regions import find_loop_regions


def test_find_loop_regions_do_while_counts_one_loop():
    source = """void f(int x) {
    do {
        work();
    } while (x);
}
"""

    regions = find_loop_regions(source)

    assert len(regions) == 1
    assert regions[0].header_line == 2
    assert regions[0].header_col == 5


def test_find_loop_regions_ignores_fake_tokens_in_comments_and_literals():
    source = (
        "void f(int n) {\n"
        "    // for (x) { while (y) do { } }\n"
        "    /* do { fake(); } while (x); */\n"
        '    const char *text = "for (x) { while (y) do { }";\n'
        "    char open = '{';\n"
        "    char close = '}';\n"
        "    for (int i = 0; i < n; ++i) {\n"
        "        work();\n"
        "    }\n"
        "}\n"
    )

    regions = find_loop_regions(source)

    assert len(regions) == 1
    assert regions[0].header_line == 7
    assert regions[0].header_col == 5
