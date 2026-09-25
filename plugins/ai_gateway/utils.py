def score_emoji(score: int) -> str:
    if score < 25:
        return "🔴"

    if score < 45:
        return "🟠"

    if score < 55:
        return "🟡"

    if score < 75:
        return "🟢"

    if score < 85:
        return "🟣"

    return "👑"