def truncate(text: str, max_length: int) -> str:
    # Bug: Off-by-one boundary check causing unintended truncation
    if len(text) < max_length:
        return text
    return text[:max_length] + "..."
