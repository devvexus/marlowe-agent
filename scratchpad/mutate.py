"""Revert the sanitiser at ONE named function and report which tests notice.

The point is discrimination, not coverage: if reverting site A and reverting site B fail the
same test, then one of the two sites has no guard of its own and the suite would stay green
with it unprotected. That is family #16 -- the property asserted somewhere other than where it
is enforced -- and it was committed once already while fixing family #16.

Usage: python mutate.py <file> <fn_name>       # writes the mutated file in place
       python mutate.py --restore <file>       # puts the original back
"""
import sys
import shutil
import pathlib

BAK = ".sanitiser-mutation-backup"


def span_of(text, fn_name):
    """Line span of `fn <fn_name>`'s body, by brace counting from its opening brace."""
    start = text.index(f"fn {fn_name}(")
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return start, j + 1
    raise SystemExit(f"unbalanced braces in {fn_name}")


def main():
    if sys.argv[1] == "--restore":
        p = pathlib.Path(sys.argv[2])
        shutil.copy(str(p) + BAK, p)
        pathlib.Path(str(p) + BAK).unlink()
        print(f"restored {p}")
        return

    path, fn_name = pathlib.Path(sys.argv[1]), sys.argv[2]
    text = path.read_text(encoding="utf-8")
    if not pathlib.Path(str(path) + BAK).exists():
        shutil.copy(path, str(path) + BAK)

    a, b = span_of(text, fn_name)
    body = text[a:b]
    n = body.count("sanitize_line(") + body.count("sanitize_prose(")
    if n == 0:
        raise SystemExit(f"NOTHING TO REVERT in {fn_name} -- the site has no sanitiser call")
    # `identity` is a true passthrough: this restores the pre-fix behaviour exactly rather than
    # breaking compilation, so a test that fails here fails on the DEFECT and not on a type error.
    body = body.replace("sanitize_line(", "std::convert::identity(")
    body = body.replace("sanitize_prose(", "std::convert::identity(")
    path.write_text(text[:a] + body + text[b:], encoding="utf-8")
    print(f"reverted {n} sanitiser call(s) in {fn_name} ({path.name})")


main()
