def greet(name: str) -> str:
    if not name.strip():
        raise ValueError("name cannot be empty")
    return f"Hello, {name}!"
