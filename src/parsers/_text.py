# src/parsers/_text.py
def text(node) -> str:
    """
    Normalize a BeautifulSoup node's text:
    - joins with single spaces
    - strips leading/trailing whitespace
    - safe if node is None
    """
    if not node:
        return ""
    # get_text(" ", strip=True) collapses whitespace; split/join removes doubles
    return " ".join(node.get_text(" ", strip=True).split())
