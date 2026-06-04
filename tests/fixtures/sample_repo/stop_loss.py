def stop_loss(price: float, pct: float = 0.02) -> float:
    return price * (1 - pct)
